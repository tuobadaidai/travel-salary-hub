<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import { useRoute } from "vue-router"
import * as echarts from "echarts"
import { api } from "../api/salary"

const route = useRoute()
const detail = ref<Record<string, unknown> | null>(null)
const reportChartEl = ref<HTMLDivElement>()
const wan = (v: unknown) => (v == null ? "-" : `${(Number(v) / 10000).toFixed(0)}万`)

interface JdSummary {
  count: number
  reliable: boolean
  p25: number
  p50: number
  p75: number
  p90: number
}

interface ReportRow {
  fiscal_year: number
  report_type: string
  avg_salary: number | null
  employees: number | null
  total_comp: number | null
  revenue: number | null
  source: string | null
  confidence: string
}

let chart: echarts.ECharts | null = null
let onResize: (() => void) | null = null

function renderReports(rows: ReportRow[]) {
  if (!reportChartEl.value || !rows.length) return
  const hasComp = rows.some(r => r.total_comp)
  const hasRev = rows.some(r => r.revenue)
  chart?.dispose()
  if (onResize) window.removeEventListener("resize", onResize)
  chart = echarts.init(reportChartEl.value)
  const series: echarts.SeriesOption[] = [
    { name: "员工数", type: "bar", data: rows.map(r => r.employees ?? 0),
      itemStyle: { color: "#6a8df5" } },
  ]
  const yAxis: echarts.YAXisComponentOption[] = [{ type: "value", name: "员工数" }]
  if (hasComp || hasRev) {
    yAxis.push({ type: "value", name: "万元", position: "right" })
    if (hasComp) {
      series.push({ name: "人均人力成本(万)", type: "line", yAxisIndex: 1,
        data: rows.map(r => r.total_comp && r.employees ? +(r.total_comp / r.employees / 10000).toFixed(1) : null),
        itemStyle: { color: "#ee6666" } })
    }
    if (hasRev) {
      series.push({ name: "人均营收(万)", type: "line", yAxisIndex: 1,
        data: rows.map(r => r.revenue && r.employees ? +(r.revenue / r.employees / 10000).toFixed(0) : null),
        itemStyle: { color: "#91cc75" } })
    }
  }
  chart.setOption({
    tooltip: { trigger: "axis" },
    legend: { top: 0 },
    grid: { left: 60, right: 60, top: 40, bottom: 30 },
    xAxis: { type: "category", data: rows.map(r => r.fiscal_year) },
    yAxis,
    series,
  })
  onResize = () => chart?.resize()
  window.addEventListener("resize", onResize)
}

onMounted(async () => {
  detail.value = (await api.http.get(`/companies/${route.params.id}`)).data
  await nextTick()
  renderReports((detail.value!.reports as ReportRow[]) ?? [])
})

onBeforeUnmount(() => {
  chart?.dispose()
  if (onResize) window.removeEventListener("resize", onResize)
})
</script>

<template>
  <div v-if="detail" class="detail">
    <el-page-header :content="String(detail.name)" @back="$router.back()" />
    <el-descriptions :column="4" border class="desc">
      <el-descriptions-item label="类型">{{ detail.company_type }}</el-descriptions-item>
      <el-descriptions-item label="总部国家">{{ detail.hq_country }}</el-descriptions-item>
      <el-descriptions-item label="上市">{{ detail.is_listed ? "是" : "否" }}</el-descriptions-item>
      <el-descriptions-item label="股票代码">{{ detail.stock_code || "-" }}</el-descriptions-item>
    </el-descriptions>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>人效趋势（员工数 / 人均人力成本 / 人均营收）</template>
          <div ref="reportChartEl" class="chart" />
          <p class="chart-note">
            人均人力成本 = 年报「支付给职工以及为职工支付的现金」÷ 员工数（现金口径，含社保公积金，
            与 JD 现金总包口径不同）。人均营收受收入确认口径影响（旅行社净额法偏低）。
          </p>
        </el-card>
      </el-col>
      <el-col :span="12">
        <el-card shadow="never">
          <template #header>该公司 JD 薪酬摘要（CNY 折算）</template>
          <div v-if="detail.jd_summary" class="jd-sum">
            <div>样本 {{ (detail.jd_summary as JdSummary).count }} 条{{ (detail.jd_summary as JdSummary).reliable ? "" : "（不足5，仅供参考）" }}</div>
            <div>P25 {{ wan((detail.jd_summary as JdSummary).p25) }} · P50 {{ wan((detail.jd_summary as JdSummary).p50) }}</div>
            <div>P75 {{ wan((detail.jd_summary as JdSummary).p75) }} · P90 {{ wan((detail.jd_summary as JdSummary).p90) }}</div>
          </div>
          <el-empty v-else description="暂无 JD 薪酬记录" />
        </el-card>
      </el-col>
    </el-row>

    <el-card shadow="never">
      <template #header>财报/统计数据</template>
      <el-table :data="detail.reports as ReportRow[]" stripe>
        <el-table-column prop="fiscal_year" label="年度" width="90" />
        <el-table-column prop="report_type" label="类型" width="150" />
        <el-table-column label="人均人力成本" width="130" align="right">
          <template #default="{ row }">{{ wan(row.avg_salary) }}</template>
        </el-table-column>
        <el-table-column label="人均营收" width="120" align="right">
          <template #default="{ row }">
            {{ row.revenue && row.employees ? (row.revenue / row.employees / 10000).toFixed(0) + "万" : "—" }}
          </template>
        </el-table-column>
        <el-table-column label="营收" width="120" align="right">
          <template #default="{ row }">{{ row.revenue ? (row.revenue / 1e8).toFixed(1) + "亿" : "—" }}</template>
        </el-table-column>
        <el-table-column prop="employees" label="员工数" width="100" align="right" />
        <el-table-column prop="source" label="来源" min-width="180" />
        <el-table-column prop="confidence" label="置信度" width="90" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 16px; }
.chart { height: 320px; }
.chart-note { color: #909399; font-size: 12px; margin: 8px 0 0; line-height: 1.6; }
.jd-sum { display: flex; flex-direction: column; gap: 8px; font-size: 15px; padding: 16px 0; }
</style>
