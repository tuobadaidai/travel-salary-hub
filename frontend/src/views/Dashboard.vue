<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { ElMessage } from "element-plus"
import * as echarts from "echarts"
import {
  api, DIMENSIONS, type Meta, type QuantileItem, type Heatmap, type DrillRecord,
} from "../api/salary"
import { useFilterStore } from "../stores/filters"

const store = useFilterStore()
const meta = ref<Meta | null>(null)
const familyChartEl = ref<HTMLDivElement>()
const typeChartEl = ref<HTMLDivElement>()
const heatChartEl = ref<HTMLDivElement>()
const wan = (v: number) => `${(v / 10000).toFixed(0)}万`

// 交叉热力状态
const rowDim = ref("job_family")
const colDim = ref("city")
const heat = ref<Heatmap | null>(null)

// 穿透抽屉
const drawer = ref(false)
const drillTitle = ref("")
const drillRows = ref<DrillRecord[]>([])

const familyName = computed(
  () => (id: string) => meta.value?.job_families.find(f => String(f.id) === id)?.name ?? id,
)

function renderBox(el: HTMLDivElement | undefined, data: QuantileItem[], labelFn: (k: string) => string) {
  if (!el || !data.length) return
  const chart = echarts.init(el)
  const rows = [...data].reverse()
  const categories = rows.map(d => labelFn(d.group_key))
  chart.setOption({
    tooltip: {
      trigger: "item",
      formatter: (p: { seriesType: string; dataIndex: number }) => {
        if (p.seriesType === "scatter") {
          const d = rows[p.dataIndex]
          return `<b>${labelFn(d.group_key)}</b><br/>样本: ${d.count}${d.reliable ? "" : "（不足5，仅供参考）"}<br/>P25: ${wan(d.p25)} / P50: ${wan(d.p50)}<br/>P75: ${wan(d.p75)} / P90: ${wan(d.p90)}`
        }
        return ""
      },
    },
    grid: { left: 100, right: 40, top: 10, bottom: 30 },
    xAxis: { type: "value", axisLabel: { formatter: wan } },
    yAxis: { type: "category", data: categories },
    series: [
      { name: "P25前", type: "bar", stack: "q", itemStyle: { color: "transparent" }, barWidth: 18,
        data: rows.map(d => d.p25), silent: true, tooltip: { show: false } },
      { name: "P25-P75", type: "bar", stack: "q", barWidth: 18,
        itemStyle: { color: (p: { dataIndex: number }) => (rows[p.dataIndex].reliable ? "#6a8df5" : "#c8ccd4") },
        data: rows.map(d => d.p75 - d.p25) },
      { name: "P75-P90", type: "bar", stack: "q", barWidth: 6,
        itemStyle: { color: (p: { dataIndex: number }) => (rows[p.dataIndex].reliable ? "#b9c9f9" : "#dde0e6") },
        data: rows.map(d => d.p90 - d.p75) },
      { name: "P50", type: "scatter", symbolSize: 9, symbol: "diamond",
        itemStyle: { color: "#1f2d5c" },
        data: rows.map(d => [d.p50, d.group_key]) },
    ],
  })
  const onResize = () => chart.resize()
  window.addEventListener("resize", onResize)
}

function renderHeat() {
  const el = heatChartEl.value
  const h = heat.value
  if (!el || !h || !h.row_keys.length) return
  const chart = echarts.init(el)
  const data: [number, number, number, number, boolean][] = []
  h.grid.forEach((row, ri) =>
    row.forEach((cell, ci) => {
      if (cell) data.push([ci, ri, cell.p50, cell.count, cell.reliable])
    }))
  chart.setOption({
    tooltip: {
      formatter: (p: { data: [number, number, number, number, boolean] }) => {
        const [ci, ri, p50, count, reliable] = p.data
        return `<b>${h.row_keys[ri]} × ${h.col_keys[ci]}</b><br/>P50 年薪: ${wan(p50)}<br/>样本: ${count}${reliable ? "" : "（不足5）"}<br/><i>点击查看明细</i>`
      },
    },
    grid: { left: 110, right: 30, top: 10, bottom: 90 },
    xAxis: { type: "category", data: h.col_keys, axisLabel: { rotate: 45, fontSize: 11 } },
    yAxis: { type: "category", data: h.row_keys },
    visualMap: {
      min: 0, max: Math.max(...data.map(d => d[2]), 100000), calculable: false,
      orient: "horizontal", left: "center", bottom: 0, itemHeight: 60,
      inRange: { color: ["#eef2f9", "#b9c9e8", "#6a8df5", "#2c4a86", "#16233f"] },
      text: ["P50 高", "低"], textStyle: { fontSize: 11 },
    },
    series: [{
      type: "heatmap", data,
      label: { show: true, formatter: (p: { data: [number, number, number, number, boolean] }) => wan(p.data[2]), fontSize: 10 },
    }],
  })
  chart.on("click", (p: unknown) => {
    const d = (p as { data?: [number, number, number, number, boolean] }).data
    if (!d) return
    void openDrill(h.row_keys[d[1]], h.col_keys[d[0]])
  })
  const onResize = () => chart.resize()
  window.addEventListener("resize", onResize)
}

async function openDrill(rowKey: string, colKey: string) {
  try {
    if (rowDim.value === "job_family") {
      // 记录接口按 position 过滤；岗位族退化为城市明细
      drillTitle.value = `${rowKey} × ${colKey} 明细`
      drillRows.value = await api.records({ city: colKey, limit: 80 })
    } else if (rowDim.value === "level") {
      drillTitle.value = `${rowKey} × ${colKey} 明细`
      drillRows.value = await api.records({ level: rowKey, city: colKey, limit: 80 })
    } else if (rowDim.value === "position") {
      drillTitle.value = `${rowKey} × ${colKey} 明细`
      drillRows.value = await api.records({ position: rowKey, city: colKey, limit: 80 })
    } else {
      drillTitle.value = `${rowKey} × ${colKey} 明细`
      drillRows.value = await api.records({ city: colKey, limit: 80 })
    }
    drawer.value = true
  } catch (e) {
    ElMessage.error("穿透加载失败: " + (e as Error).message)
  }
}

async function loadHeat() {
  heat.value = await api.heatmap({ row_dim: rowDim.value, col_dim: colDim.value })
  renderHeat()
}

async function load() {
  try {
    const params = store.toParams()
    const [f, t] = await Promise.all([
      api.quantiles({ ...params, group_by: "job_family" }),
      api.quantiles({ ...params, group_by: "company_type" }),
    ])
    renderBox(familyChartEl.value, f, id => familyName.value(id))
    renderBox(typeChartEl.value, t, k => k)
  } catch (e) {
    ElMessage.error("加载失败: " + (e as Error).message)
  }
}

onMounted(async () => {
  meta.value = await api.meta()
  await Promise.all([load(), loadHeat()])
})
watch(() => [store.cities, store.country, store.companyType, store.jobFamilyId, store.dateRange], load, { deep: true })
watch([rowDim, colDim], loadHeat)
</script>

<template>
  <div class="dash">
    <el-card class="filter-card" shadow="never">
      <el-select v-model="store.cities" multiple collapse-tags placeholder="城市" clearable style="width: 200px">
        <el-option v-for="c in meta?.cities ?? []" :key="c" :label="c" :value="c" />
      </el-select>
      <el-select v-model="store.country" placeholder="国家" clearable style="width: 120px">
        <el-option v-for="c in meta?.countries ?? []" :key="c" :label="c" :value="c" />
      </el-select>
      <el-select v-model="store.companyType" placeholder="公司类型" clearable style="width: 140px">
        <el-option v-for="t in meta?.company_types ?? []" :key="t" :label="t" :value="t" />
      </el-select>
      <el-select v-model="store.jobFamilyId" placeholder="岗位族" clearable style="width: 160px">
        <el-option v-for="f in meta?.job_families ?? []" :key="f.id" :label="f.name" :value="f.id" />
      </el-select>
      <span class="data-note">共 {{ meta?.total_records ?? 0 }} 条 · 数据截至 {{ meta?.latest_collect_date ?? "-" }}</span>
      <el-button text @click="store.reset()">重置</el-button>
    </el-card>

    <el-row :gutter="16">
      <el-col :span="14">
        <el-card shadow="never">
          <template #header>岗位族年薪分位数（CNY 折算）· 深色菱形=P50</template>
          <div ref="familyChartEl" class="chart" />
        </el-card>
      </el-col>
      <el-col :span="10">
        <el-card shadow="never">
          <template #header>公司类型对比</template>
          <div ref="typeChartEl" class="chart" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>
        <div class="heat-head">
          <span>交叉透视 · 点击格子穿透明细</span>
          <div class="dim-picks">
            <el-select v-model="rowDim" style="width: 110px" size="small">
              <el-option v-for="d in DIMENSIONS" :key="d.value" :label="`行: ${d.label}`" :value="d.value" />
            </el-select>
            <span class="x">×</span>
            <el-select v-model="colDim" style="width: 110px" size="small">
              <el-option v-for="d in DIMENSIONS" :key="d.value" :label="`列: ${d.label}`" :value="d.value" />
            </el-select>
          </div>
        </div>
      </template>
      <div ref="heatChartEl" class="heat" />
    </el-card>

    <el-drawer v-model="drawer" :title="drillTitle" size="56%">
      <el-table :data="drillRows" size="small" stripe>
        <el-table-column prop="position" label="岗位" width="130" show-overflow-tooltip />
        <el-table-column prop="company_name" label="数据源/公司" width="120" show-overflow-tooltip />
        <el-table-column prop="level" label="级别" width="60" />
        <el-table-column prop="salary_range" label="月薪区间" width="110" />
        <el-table-column label="年薪CNY" width="90">
          <template #default="{ row }">{{ row.annual_cny ? wan(row.annual_cny) : "-" }}</template>
        </el-table-column>
        <el-table-column prop="source" label="来源" width="110" />
        <el-table-column label="证据">
          <template #default="{ row }">
            <a v-if="row.source_url" :href="row.source_url" target="_blank" rel="noopener" class="ev-link">原文</a>
            <span v-else class="ev-none">CSV</span>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>
  </div>
</template>

<style scoped>
.dash { display: flex; flex-direction: column; gap: 16px; }
.filter-card :deep(.el-card__body) { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.data-note { color: #909399; font-size: 13px; margin-left: auto; }
.chart { height: 420px; }
.heat { height: 460px; }
.heat-head { display: flex; align-items: center; justify-content: space-between; }
.dim-picks { display: flex; align-items: center; gap: 8px; font-weight: 400; }
.x { color: #909399; }
.ev-link { color: #3d6db3; }
.ev-none { color: #c0c4cc; font-size: 12px; }
</style>
