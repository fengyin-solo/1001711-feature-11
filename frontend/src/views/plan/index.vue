<template>
  <section class="page" data-module="plan">
    <header class="page-head">
      <div>
        <h2>点检计划管理</h2>
        <p class="page-desc">维护点检计划，围绕计划编号、点检对象、点检周期、点检项目做登记、筛选与状态流转。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记点检计划</button>
        <button class="btn" type="button" @click="exportRows">导出点检计划清单</button>
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
            <template v-if="String(row.status) === '已作废'">
              <span class="muted-text">已作废</span>
            </template>
            <button
              v-for="action in availableActions(row)"
              v-else
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无点检计划数据，可先登记点检计划</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条点检计划记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/plan'
const columns = ["计划编号", "点检对象", "点检周期", "点检项目", "计划工期", "编制人员", "审批人员", "计划状态"]
const actionByStatus: Record<string, string[]> = {
  '待编制': ['提交审批', '作废计划'],
  '待审批': ['确认批复', '作废计划'],
  '已批复': ['作废计划'],
  '已作废': [],
}
const statuses = ["待编制", "待审批", "已批复", "已作废"]
const stats = [{"label": "待审批计划", "value": 0}, {"label": "已批复计划", "value": 0}, {"label": "本月点检项", "value": 0}]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)

function displayValue(row: Row, column: string) {
  if (column === '计划状态') return row.status ?? row[column] ?? '—'
  return row[column] ?? '—'
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
  errorMessage.value = '点检计划登记入口尚未接入审批流'
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values: { action } }),
    })
    const payload = await response.json().catch(() => null)
    if (!response.ok || payload?.ok === false) {
      throw new Error(payload?.message ?? payload?.detail ?? '点检计划动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检计划操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams(filters.value as Record<string, string>).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('点检计划列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '点检计划列表读取失败'
  }
}

onMounted(reload)
</script>
