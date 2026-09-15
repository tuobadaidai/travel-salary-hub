<script setup lang="ts">
import { onMounted, ref } from "vue"
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
  source: string | null
  confidence: string
}

function renderReports(rows: ReportRow[]) {
  if (!reportChartEl.value || !rows.length) return
  const chart = echarts.init(reportChartEl.value)
  chart.setOption({
    tooltip: { trigger: "axis" },
    grid: { left: 60, right: 40, top: 30, bottom: 30 },
    xAxis: { type: "category", data: rows.map(r => r.fiscal_year) },
    yAxis: [{ type: "value", name: "员工数" }],
    series: [
      { name: "员工数", type: "bar", data: rows.map(r => r.employees ?? 0),
        itemStyle: { color: "#6a8df5" } },
    ],
  })
  window.addEventListener("resize", () => chart.resize())
}

onMounted(async () => {
  detail.value = (await api.http.get(`/companies/${route.params.id}`)).data
  renderReports((detail.value!.reports as ReportRow[]) ?? [])
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
          <template #header>财报披露员工数</template>
          <div ref="reportChartEl" class="chart" />
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
        <el-table-column label="人均薪酬" width="120">
          <template #default="{ row }">{{ wan(row.avg_salary) }}</template>
        </el-table-column>
        <el-table-column prop="employees" label="员工数" width="110" />
        <el-table-column prop="source" label="来源" min-width="180" />
        <el-table-column prop="confidence" label="置信度" width="90" />
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.detail { display: flex; flex-direction: column; gap: 16px; }
.chart { height: 300px; }
.jd-sum { display: flex; flex-direction: column; gap: 8px; font-size: 15px; padding: 16px 0; }
</style>
