<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue"
import { ElMessage } from "element-plus"
import * as echarts from "echarts"
import {
  api, type Meta, type QuantileItem, type ExecSummary, type DrillRecord,
} from "../api/salary"

const meta = ref<Meta | null>(null)
const exec = ref<ExecSummary | null>(null)
const loading = ref(true)

const wan = (v: number | null | undefined) => v == null ? "—" : (v / 10000).toFixed(1)
const wan0 = (v: number | null | undefined) => v == null ? "—" : (v / 10000).toFixed(0)

// ECharts 实例统一管理
const charts: echarts.ECharts[] = []
const resizeHandlers: (() => void)[] = []
const waterEl = ref<HTMLDivElement>()
const effEl = ref<HTMLDivElement>()
const structEl = ref<HTMLDivElement>()

function mountChart(el: HTMLDivElement): echarts.ECharts {
  const chart = echarts.init(el)
  charts.push(chart)
  const onResize = () => chart.resize()
  window.addEventListener("resize", onResize)
  resizeHandlers.push(() => window.removeEventListener("resize", onResize))
  return chart
}
function disposeCharts() {
  resizeHandlers.forEach(fn => fn())
  resizeHandlers.length = 0
  charts.forEach(c => c.dispose())
  charts.length = 0
}

// ---------- KPI ----------
const effRated = computed(() =>
  (exec.value?.efficiency.companies ?? []).filter(c => c.rev_per_comp != null))

const kpis = computed(() => {
  const lv = exec.value?.positioning.levels ?? []
  const eff = exec.value?.efficiency.companies ?? []
  const gaps = lv.filter(l => l.gap_pct != null)
  const above = gaps.filter(l => (l.gap_pct ?? 0) > 0.1).map(l => l.level)
  const below = gaps.filter(l => (l.gap_pct ?? 0) < -0.1).map(l => l.level)
  const withEff = eff.filter(c => c.avg_comp_wan != null && c.avg_rev_wan != null)
  const effAvg = withEff.length
    ? withEff.reduce((s, c) => s + (c.rev_per_comp ?? 0), 0) / withEff.length
    : null
  return {
    totalMarket: meta.value?.total_records ?? 0,
    didaCount: lv.reduce((s, l) => s + (l.dida?.count ?? 0), 0),
    above, below,
    effMedian: effAvg ? `${effAvg.toFixed(1)}x` : "—",
    effCount: withEff.length,
    effAll: eff.length,
  }
})

// ---------- 板块1：薪酬水位定位 ----------
const gapCls = (g: number | null) => g == null ? "flat" : Math.abs(g) < 0.1 ? "flat" : g > 0 ? "up" : "down"
const gapTxt = (g: number | null) => g == null ? "—" : (g > 0 ? "+" : "") + (g * 100).toFixed(0) + "%"

function renderWaterfall() {
  const el = waterEl.value
  const data = exec.value?.positioning.levels ?? []
  if (!el || !data.length) return
  const chart = mountChart(el)
  const names = data.map(l => l.level)
  const mk = (pick: (q: QuantileItem) => number | null) =>
    data.map(l => pick(l.dida ?? l.market!) ?? 0)
  chart.setOption({
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      formatter: (ps: unknown) => {
        const params = ps as { seriesName: string; value: number; axisValue: string }[]
        const lv = data.find(l => l.level === params[0].axisValue)
        if (!lv) return ""
        const fmt = (q: QuantileItem | null) =>
          q ? `P25 ${wan(q.p25)}万 · P50 <b>${wan(q.p50)}万</b> · P75 ${wan(q.p75)}万 (n=${q.count})` : "—"
        return `<b>${lv.level}</b><br/>DIDA 内部: ${fmt(lv.dida)}<br/>市场参照: ${fmt(lv.market)}<br/>水位差: <b>${gapTxt(lv.gap_pct)}</b>`
      },
    },
    legend: { top: 0, textStyle: { fontSize: 11 } },
    grid: { left: 50, right: 30, top: 34, bottom: 26 },
    xAxis: { type: "category", data: names, axisLabel: { fontSize: 12 } },
    yAxis: { type: "value", axisLabel: { formatter: wan0 }, name: "年薪(万)" },
    series: [
      { name: "P25", type: "bar", barWidth: 16, itemStyle: { color: "#B7CBE8" }, data: mk(q => q?.p25 ?? null) },
      { name: "P50", type: "bar", barWidth: 16, itemStyle: { color: "#5B8DEF" }, data: mk(q => q?.p50 ?? null) },
      { name: "P75", type: "bar", barWidth: 16, itemStyle: { color: "#1F3D7A" }, data: mk(q => q?.p75 ?? null) },
    ],
  })
}

// ---------- 板块2：人效分析（麦肯锡: 人力资本投入产出）----------
function renderEfficiency() {
  const el = effEl.value
  const companies = exec.value?.efficiency.companies ?? []
  if (!el || !companies.length) return
  const chart = mountChart(el)
  const barData = companies.map(c => ({
    name: c.company,
    value: c.avg_comp_wan,
    itemStyle: { color: c.avg_comp_wan != null ? "#0E7C7B" : "#C9D2DE" },
  }))
  const lineData = companies.map(c => c.avg_rev_wan)
  chart.setOption({
    tooltip: {
      trigger: "axis",
      formatter: (ps: unknown) => {
        const params = ps as { axisValue: string; seriesName: string; value: number }[]
        const c = companies.find(x => x.company === params[0].axisValue)
        if (!c) return ""
        const parts = [`<b>${c.company}</b>`, `员工 ${c.employees.toLocaleString()} 人`]
        if (c.revenue_yi != null) parts.push(`营收 ${c.revenue_yi} 亿`)
        if (c.total_comp_yi != null) parts.push(`人力成本 ${c.total_comp_yi} 亿`)
        if (c.avg_comp_wan != null) parts.push(`人均人力成本 <b>${c.avg_comp_wan} 万</b>`)
        if (c.avg_rev_wan != null) parts.push(`人均营收 <b>${c.avg_rev_wan} 万</b>`)
        if (c.rev_per_comp != null) parts.push(`投入产出比 <b>${c.rev_per_comp}x</b>`)
        return parts.join("<br/>")
      },
    },
    legend: { top: 0, textStyle: { fontSize: 11 } },
    grid: { left: 50, right: 60, top: 34, bottom: 60 },
    xAxis: { type: "category", data: companies.map(c => c.company), axisLabel: { fontSize: 11, rotate: 20 } },
    yAxis: [
      { type: "value", name: "人均成本(万)", axisLabel: { formatter: (v: number) => v.toFixed(0) } },
      { type: "value", name: "人均营收(万)", axisLabel: { formatter: (v: number) => v.toFixed(0) } },
    ],
    series: [
      { name: "人均人力成本", type: "bar", barWidth: 22, data: barData },
      { name: "人均营收", type: "line", yAxisIndex: 1, symbolSize: 8, lineStyle: { width: 2.5, color: "#E8A33D" }, itemStyle: { color: "#E8A33D" }, data: lineData },
    ],
  })
}

// ---------- 板块3：岗位族 × 级别 市场水位矩阵 ----------
const structSort = ref<"p50" | "count">("p50")
const sortedFamilies = computed(() => {
  const m = exec.value?.matrix.matrix ?? {}
  const fams = exec.value?.matrix.families ?? []
  return [...fams].sort((a, b) => {
    const pa = Math.max(0, ...Object.values(m[a] ?? {}).map(q => structSort.value === "p50" ? q.p50 : q.count))
    const pb = Math.max(0, ...Object.values(m[b] ?? {}).map(q => structSort.value === "p50" ? q.p50 : q.count))
    return pb - pa
  })
})

function renderStructure() {
  const el = structEl.value
  const m = exec.value?.matrix.matrix ?? {}
  const fams = sortedFamilies.value
  const levels = exec.value?.matrix.levels ?? []
  if (!el || !fams.length) return
  const chart = mountChart(el)
  const data: [number, number, number, number, boolean][] = []
  fams.forEach((fam, ri) => {
    levels.forEach((lv, ci) => {
      const q = m[fam]?.[lv]
      if (q) data.push([ci, ri, q.p50, q.count, q.reliable])
    })
  })
  chart.setOption({
    tooltip: {
      formatter: (p: { data: [number, number, number, number, boolean] }) => {
        const [ci, ri, p50, count, reliable] = p.data
        return `<b>${fams[ri]} × ${levels[ci]}</b><br/>市场 P50 年薪: <b>${wan(p50)}万</b><br/>样本: ${count}${reliable ? "" : "（不足5，仅供参考）"}`
      },
    },
    grid: { left: 110, right: 110, top: 10, bottom: 70 },
    xAxis: { type: "category", data: levels, axisLabel: { fontSize: 12 } },
    yAxis: { type: "category", data: fams, axisLabel: { fontSize: 12 } },
    visualMap: {
      min: 0, max: Math.max(...data.map(d => d[2]), 400000), calculable: false,
      orient: "vertical", right: 0, top: "center", itemHeight: 120,
      inRange: { color: ["#F0F5FB", "#B7CBE8", "#5B8DEF", "#1F3D7A"] },
      text: ["P50 高", "低"], textStyle: { fontSize: 11 },
    },
    series: [{
      type: "heatmap", data,
      label: {
        show: true, fontSize: 10.5,
        formatter: (p: { data: [number, number, number, number, boolean] }) => wan0(p.data[2]),
        color: "#1B2635",
      },
      itemStyle: {
        borderColor: (p: { data: [number, number, number, number, boolean] }) => (p.data[4] ? "#fff" : "#F5A6A6"),
        borderWidth: 1.5,
      },
    }],
  })
  chart.on("click", (p: { data?: unknown }) => {
    const d = p.data as [number, number, number, number, boolean] | undefined
    if (d) openDrill(fams[d[1]], levels[d[0]])
  })
}

// ---------- 穿透抽屉（保留证据链）----------
const drawer = ref(false)
const drillTitle = ref("")
const drillRows = ref<DrillRecord[]>([])
async function openDrill(fam: string, lv: string) {
  drillTitle.value = `${fam} × ${lv} 市场明细`
  try {
    drillRows.value = await api.records({ level: lv, limit: 80 })
    drawer.value = true
  } catch (e) {
    ElMessage.error("穿透加载失败: " + (e as Error).message)
  }
}

onMounted(async () => {
  try {
    const [m, ex] = await Promise.all([api.meta(), api.execSummary()])
    meta.value = m
    exec.value = ex
  } catch (e) {
    ElMessage.error("加载失败: " + (e as Error).message)
  } finally {
    loading.value = false
  }
  renderWaterfall()
  renderEfficiency()
  renderStructure()
})
onBeforeUnmount(disposeCharts)
</script>

<template>
  <div class="dash" v-loading="loading">
    <!-- ═══ 执行摘要：核心结论 ═══ -->
    <div class="exec-bar">
      <div class="exec-title">
        <h2>薪酬对标执行摘要</h2>
        <p>内部 {{ kpis.didaCount }} 人薪酬水位 × {{ kpis.totalMarket }} 条市场数据 × {{ exec?.efficiency.companies.length ?? 0 }} 家上市公司人效</p>
      </div>
      <div class="kpi-row">
        <div class="kpi">
          <div class="k-l">薪酬水位总览</div>
          <div class="k-v">
            <span class="num up">{{ kpis.above.length }}</span> 高于市场 /
            <span class="num down">{{ kpis.below.length }}</span> 低于市场
          </div>
          <div class="k-s">{{ kpis.above.length ? `${kpis.above.join("、")} 高于市场带` : "各档位与市场基本持平" }}</div>
        </div>
        <div class="kpi">
          <div class="k-l">人效投入产出</div>
          <div class="k-v"><span class="num">{{ kpis.effMedian }}</span></div>
          <div class="k-s">{{ kpis.effCount }}/{{ kpis.effAll }} 家公司披露完整（营收/人力成本）</div>
        </div>
        <div class="kpi">
          <div class="k-l">数据覆盖</div>
          <div class="k-v"><span class="num">{{ exec?.matrix.families.length ?? 0 }}</span> 岗位族 × {{ exec?.matrix.levels.length ?? 0 }} 级别</div>
          <div class="k-s">市场参照样本 {{ kpis.totalMarket }} 条 · 更新至 {{ meta?.latest_collect_date ?? "—" }}</div>
        </div>
      </div>
    </div>

    <!-- ═══ 板块一：薪酬水位定位 ═══ -->
    <section class="panel">
      <div class="panel-head">
        <div>
          <span class="sec-tag">01</span>
          <h3>薪酬水位定位</h3>
          <p class="sub">DIDA 内部各级别年薪分位 vs 市场参照带 —— 差距 &gt;±10% 触发定薪审视</p>
        </div>
      </div>
      <div class="water-grid">
        <div ref="waterEl" class="chart water-chart" />
        <div class="verdict-list">
          <div v-for="l in exec?.positioning.levels ?? []" :key="l.level" class="v-row">
            <div class="v-lv">{{ l.level }}<span class="v-n">{{ l.dida ? `n=${l.dida.count}` : "" }}</span></div>
            <div class="v-nums">
              <span class="v-d">DIDA P50 <b>{{ wan(l.dida?.p50) }}万</b></span>
              <span class="v-m">市场 P50 <b>{{ wan(l.market?.p50) }}万</b></span>
            </div>
            <span class="v-gap" :class="gapCls(l.gap_pct)">{{ gapTxt(l.gap_pct) }}</span>
            <span class="v-verdict" :class="gapCls(l.gap_pct)">{{ l.verdict }}</span>
          </div>
        </div>
      </div>
      <p class="footnote">* 市场分位基于公开招聘数据聚合（P25/P50/P75），主管/经理档市场样本以初级岗位居多，水位差偏大需结合岗位结构解读；总监档市场样本 n=50 可靠。</p>
    </section>

    <!-- ═══ 板块二：人效分析 ═══ -->
    <section class="panel">
      <div class="panel-head">
        <div>
          <span class="sec-tag">02</span>
          <h3>人效分析 · 人力资本投入产出</h3>
          <p class="sub">人均人力成本（投入）× 人均营收（产出）—— 薪酬策略的财务约束</p>
        </div>
      </div>
      <div ref="effEl" class="chart eff-chart" />
      <div class="eff-notes">
        <div class="note-card" v-for="c in effRated" :key="c.company">
          <div class="n-head">
            <b>{{ c.company }}</b>
            <span class="n-ratio" :class="(c.rev_per_comp ?? 0) >= 5 ? 'good' : (c.rev_per_comp ?? 0) >= 3 ? 'mid' : 'warn'">{{ c.rev_per_comp }}x</span>
          </div>
          <div class="n-body">人均成本 {{ c.avg_comp_wan }}万 → 人均营收 {{ c.avg_rev_wan ?? "—" }}万</div>
        </div>
      </div>
      <p class="footnote">* 人均人力成本 = 现金流量表「支付给职工的现金」÷ 员工数（含社保公积金，现金口径）；人均营收受收入确认方式影响（OTA 净额法 vs 平台总额法），跨公司对比看趋势不看绝对值。</p>
    </section>

    <!-- ═══ 板块三：薪酬结构 ═══ -->
    <section class="panel">
      <div class="panel-head">
        <div>
          <span class="sec-tag">03</span>
          <h3>薪酬结构 · 岗位族 × 级别市场水位</h3>
          <p class="sub">市场 P50 矩阵 —— 定薪锚点；红框=样本&lt;5 仅供参考，点击穿透明细</p>
        </div>
        <div class="sort-switch">
          排序：
          <span class="chip" :class="{ on: structSort === 'p50' }" @click="structSort = 'p50'; renderStructure()">按水位</span>
          <span class="chip" :class="{ on: structSort === 'count' }" @click="structSort = 'count'; renderStructure()">按样本</span>
        </div>
      </div>
      <div ref="structEl" class="chart struct-chart" @click="() => {}" />
    </section>

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
.dash { display: flex; flex-direction: column; gap: 18px; }

/* 执行摘要条 */
.exec-bar {
  background: linear-gradient(135deg, #10263F 0%, #1B2635 100%);
  color: #fff; border-radius: 12px; padding: 22px 26px;
  display: flex; gap: 32px; align-items: stretch;
}
.exec-title h2 { font-size: 19px; font-weight: 650; margin: 0 0 6px; }
.exec-title p { font-size: 12.5px; color: #8FA3BC; margin: 0; }
.kpi-row { margin-left: auto; display: flex; gap: 28px; }
.kpi { min-width: 190px; }
.kpi .k-l { font-size: 11.5px; color: #8FA3BC; letter-spacing: 0.5px; }
.kpi .k-v { font-size: 14px; margin-top: 6px; }
.kpi .num { font-size: 26px; font-weight: 700; }
.kpi .num.up { color: #E8A33D; }
.kpi .num.down { color: #5FC49E; }
.kpi .k-s { font-size: 11px; color: #6E829B; margin-top: 5px; line-height: 1.5; }

/* 面板 */
.panel { background: #fff; border: 1px solid #E4E6EB; border-radius: 12px; padding: 20px 24px; }
.panel-head { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 8px; }
.panel-head h3 { font-size: 16px; font-weight: 650; margin: 0; display: inline; }
.panel-head .sub { font-size: 12.5px; color: #8A94A3; margin: 4px 0 0; }
.sec-tag {
  display: inline-block; background: #0E7C7B; color: #fff; font-size: 11px; font-weight: 700;
  border-radius: 4px; padding: 1px 7px; margin-right: 8px; vertical-align: 2px;
}
.chart { width: 100%; }
.water-chart { height: 320px; }
.eff-chart { height: 340px; }
.struct-chart { height: 380px; }
.water-grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 20px; }

/* 水位判定列表 */
.verdict-list { display: flex; flex-direction: column; gap: 0; }
.v-row {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 4px; border-bottom: 1px dashed #EAECEF;
}
.v-row:last-child { border-bottom: none; }
.v-lv { font-weight: 650; font-size: 13.5px; width: 64px; }
.v-lv .v-n { font-size: 10.5px; color: #A6ADB8; font-weight: 400; margin-left: 4px; }
.v-nums { display: flex; flex-direction: column; gap: 1px; font-size: 11.5px; color: #8A94A3; flex: 1; }
.v-nums b { color: #1B2635; font-size: 13px; }
.v-gap { font-weight: 700; font-size: 13px; width: 58px; text-align: right; }
.v-verdict {
  font-size: 11px; padding: 2px 8px; border-radius: 999px; width: 68px; text-align: center;
}
.v-gap.up, .v-verdict.up { color: #B25E09; background: #FDF3E4; }
.v-gap.down, .v-verdict.down { color: #0E7C52; background: #E2F3EA; }
.v-gap.flat, .v-verdict.flat { color: #6E7A8A; background: #F0F2F5; }

/* 人效卡片 */
.eff-notes { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 14px; }
.note-card { border: 1px solid #E4E6EB; border-radius: 8px; padding: 10px 14px; min-width: 180px; }
.n-head { display: flex; align-items: center; gap: 8px; font-size: 13px; }
.n-ratio { margin-left: auto; font-weight: 700; font-size: 13.5px; }
.n-ratio.good { color: #0E7C52; }
.n-ratio.mid { color: #B25E09; }
.n-ratio.warn { color: #C0392B; }
.n-body { font-size: 11.5px; color: #8A94A3; margin-top: 3px; }

.sort-switch { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: #8A94A3; }
.chip {
  padding: 4px 12px; border-radius: 999px; font-size: 12px;
  border: 1px solid #D9DDE3; cursor: pointer; color: #5A6474;
}
.chip.on { background: #0E7C7B; border-color: #0E7C7B; color: #fff; }

.footnote { font-size: 11.5px; color: #A6ADB8; margin: 12px 0 0; line-height: 1.6; }
.ev-link { color: #3d6db3; }
.ev-none { color: #c0c4cc; font-size: 12px; }
</style>
