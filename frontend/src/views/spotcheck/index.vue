<template>
  <section class="page" data-module="spotcheck">
    <header class="page-head">
      <div>
        <h2>点检记录管理</h2>
        <p class="page-desc">维护点检记录，围绕点检单号、关联计划、点检设备、点检人员做登记、筛选与状态流转。</p>
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
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">{{ displayValue(row, column) }}</td>
          <td class="row-actions">
            <template v-if="isPlanVoid(row)">
              <span class="muted-text">仅查看</span>
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
              <span v-if="!availableActions(row).length" class="muted-text">已提交，不可重复操作</span>
            </template>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无点检记录数据，可先登记点检记录</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条点检记录记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | boolean | null>

const ENDPOINT = '/api/spotcheck'
const columns = ["点检单号", "关联计划", "点检设备", "点检人员", "点检日期", "点检结论", "异常项数", "点检状态"]
const actionByStatus: Record<string, string[]> = {
  '待点检': ['开始点检'],
  '点检中': ['提交结果', '退回重检'],
  '已提交': [],
  '已退回': [],
}
const stats = [{"label": "待点检设备", "value": 0}, {"label": "本月点检单数", "value": 0}, {"label": "异常项数", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const planStatuses = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function displayValue(row: Row, column: string) {
  if (column === '点检状态') return row.status ?? row[column] ?? '—'
  const value = row[column]
  return value === null || value === undefined || value === '' ? '—' : value
}

function isPlanVoid(row: Row) {
  return planStatuses.value[String(row['关联计划'] ?? '')] === '已作废'
}

function availableActions(row: Row) {
  return actionByStatus[String(row.status ?? '')] ?? []
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
  const values: Record<string, string> = { action }
  if (action === '提交结果') {
    const conclusionInput = window.prompt('请输入点检结论（正常/异常）', '正常')
    if (conclusionInput === null) return
    const conclusion = conclusionInput.trim()
    values['点检结论'] = conclusion
    if (conclusion === '异常') {
      const countInput = window.prompt('请输入异常项数', '1')
      if (countInput === null) return
      values['异常项数'] = countInput.trim()
    }
  }

  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? payload?.detail ?? '点检记录动作未生效，请稍后重试')
    }
    await Promise.all([reload(), loadPlans()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检记录操作失败'
  }
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

async function loadPlans() {
  const response = await request(`/api/plan?page=1&size=200`)
  if (!response.ok) return
  const payload = await response.json().catch(() => null)
  const statusMap: Record<string, string> = {}
  for (const plan of payload?.items ?? []) {
    statusMap[String(plan['计划编号'] ?? '')] = String(plan.status ?? '')
  }
  planStatuses.value = statusMap
}

onMounted(() => {
  void Promise.all([reload(), loadPlans()])
})
</script>
