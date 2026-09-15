<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { ElMessage } from "element-plus"
import * as echarts from "echarts"
import { api, type Meta, type QuantileItem } from "../api/salary"
import { useFilterStore } from "../stores/filters"

const store = useFilterStore()
const meta = ref<Meta | null>(null)
const familyChartEl = ref<HTMLDivElement>()
const typeChartEl = ref<HTMLDivElement>()
const wan = (v: number) => `${(v / 10000).toFixed(0)}万`

const familyName = computed(
  () => (id: string) => meta.value?.job_families.find(f => String(f.id) === id)?.name ?? id,
)

function renderBox(el: HTMLDivElement | undefined, data: QuantileItem[], labelFn: (k: string) => string) {
  if (!el || !data.length) return
  const chart = echarts.init(el)
  // 倒序让第一条显示在顶部
  const rows = [...data].reverse()
  const categories = rows.map(d => labelFn(d.group_key))
  chart.setOption({
    tooltip: {
      trigger: "item",
      formatter: (p: { seriesType: string; dataIndex: number; seriesName: string }) => {
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
  await load()
})
watch(() => [store.cities, store.country, store.companyType, store.jobFamilyId, store.dateRange], load, { deep: true })
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
  </div>
</template>

<style scoped>
.dash { display: flex; flex-direction: column; gap: 16px; }
.filter-card :deep(.el-card__body) { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.data-note { color: #909399; font-size: 13px; margin-left: auto; }
.chart { height: 420px; }
</style>
