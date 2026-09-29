<template>
  <section class="page" data-module="spotcheck">
    <header class="page-head">
      <div>
        <h2>点检记录管理</h2>
        <p class="page-desc">维护点检记录，围绕点检单号、关联计划、点检设备、点检人员做登记、筛选与状态流转。点检结论异常时按异常项数生成整改事项并流转为已提交。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记点检记录</button>
        <button class="btn" type="button" @click="exportRows">导出点检记录清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>待整改</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ rectifyCount(row) }}</td>
          <td class="row-actions">
            <template v-if="isVoid(row)">
              <span class="readonly-tag">计划已作废 · 仅查看</span>
            </template>
            <template v-else>
              <button
                v-for="action in availableActions(row)"
                :key="action"
                class="link"
                type="button"
                @click="runAction(action, row)"
              >
                {{ action }}
              </button>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 2" class="empty-state">暂无点检记录数据，可先登记点检记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条点检记录记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
      <span v-else-if="successMessage" class="success-text">{{ successMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/spotcheck'
const columns = ["点检单号", "关联计划", "点检设备", "点检人员", "点检日期", "点检结论", "异常项数", "点检状态"]
const filterFields = ["点检单号", "关联计划", "点检设备"]
const ALL_ACTIONS = ["开始点检", "提交结果", "退回重检"] as const

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const successMessage = ref('')
const filters = ref<Record<string, string>>({})

const stats = computed(() => {
  const waiting = rows.value.filter((row) => row["点检状态"] === "待点检").length
  const abnormal = rows.value.reduce(
    (sum, row) => sum + (typeof row["异常项数"] === "number" ? (row["异常项数"] as number) : 0),
    0,
  )
  const rectifying = rows.value.reduce((sum, row) => sum + rectifyCount(row), 0)
  return [
    { label: "待点检设备", value: waiting },
    { label: "异常项数", value: abnormal },
    { label: "待整改事项", value: rectifying },
  ]
})

function statusOf(row: Row): string {
  return String(row["点检状态"] ?? row["status"] ?? "")
}

function isVoid(row: Row): boolean {
  return row["计划已作废"] === true
}

function rectifyCount(row: Row): number {
  return typeof row["待整改数"] === "number" ? (row["待整改数"] as number) : 0
}

function availableActions(row: Row): readonly string[] {
  if (isVoid(row)) {
    return []
  }
  switch (statusOf(row)) {
    case "待点检":
      return ["开始点检"]
    case "点检中":
      return ["提交结果", "退回重检"]
    case "已提交":
      return ["退回重检"]
    case "已退回":
      return ["提交结果"]
    default:
      return ALL_ACTIONS
  }
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  errorMessage.value = '点检记录登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  successMessage.value = ''

  const values: Record<string, string> = { action }
  if (action === "提交结果") {
    const result = window.prompt(`点检单 ${row["点检单号"] ?? ""} 的点检结论：请输入「正常」或「异常」`)
    if (result === null) {
      return
    }
    const conclusion = result.trim()
    if (!conclusion) {
      errorMessage.value = '点检结论不能为空，请重新提交'
      return
    }
    values["点检结论"] = conclusion
    if (conclusion === "异常") {
      const countText = window.prompt('结论为异常，请填写异常项数（正整数，将据此生成待整改事项）')
      if (countText === null) {
        return
      }
      const count = countText.trim()
      if (!count) {
        errorMessage.value = '点检结论为异常但异常项数为空，存在冲突，已拦下本次提交'
        return
      }
      values["异常项数"] = count
    }
  }

  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || !payload) {
      throw new Error('点检记录动作未生效，请稍后重试')
    }
    if (!payload.ok) {
      errorMessage.value = payload.message || '点检记录操作未生效'
      return
    }
    successMessage.value = buildSuccessMessage(payload)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检记录操作失败'
  }
}

function buildSuccessMessage(payload: {
  message?: string
  rectify_items?: Array<Record<string, string>>
}): string {
  const message = payload.message || '操作已生效'
  const items = payload.rectify_items ?? []
  if (!items.length) {
    return message
  }
  const codes = items.map((item) => item["整改单号"]).filter(Boolean).join("、")
  return codes ? `${message}（整改单号：${codes}）` : message
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('点检记录列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检记录列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.success-text {
  color: #067647;
}

.readonly-tag {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}
</style>
