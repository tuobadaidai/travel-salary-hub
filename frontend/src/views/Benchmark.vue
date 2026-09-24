<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import {
  api, type GradeBenchmark, type GradeCell, type GradeMeta, type PositionItem, type DrillRecord,
} from "../api/salary"

const route = useRoute()
const router = useRouter()

const positions = ref<PositionItem[]>([])
const grades = ref<GradeMeta[]>([])
const selected = ref<string>("")
const seqFilter = ref<"P" | "O" | "M" | "all">("P")
const cityFilter = ref<string[]>([])
const matrix = ref<GradeBenchmark | null>(null)
const loading = ref(false)

// 抽屉
const drawer = ref(false)
const drillTitle = ref("")
const drillSub = ref("")
const drillRows = ref<DrillRecord[]>([])

const wan = (v: number | null | undefined) => v == null ? "—" : (v / 10000).toFixed(1)

const visibleGrades = computed(() => {
  if (seqFilter.value === "all") return grades.value
  return grades.value.filter(g => g.seq === seqFilter.value)
})
const cities = computed(() => {
  const all = matrix.value?.cities ?? []
  return cityFilter.value.length ? all.filter(c => cityFilter.value.includes(c)) : all
})

function cell(g: string, ct: string): GradeCell | null {
  return matrix.value?.cells?.[g]?.[ct] ?? null
}
function hasData(c: GradeCell | null): boolean {
  return !!(c && (c.dida || c.market_ref))
}

const TIER_TIP: Record<number, string> = {
  1: "本职级 × 本城市 DIDA 样本 ≥5，直接对标同城市场",
  2: "本城市样本不足，展示本职级全国 P50（样本≥5），市场参照为全国同级别带",
  3: "DIDA 样本不足 5，仅展示市场级别带参照（内部数字灰显仅供参考）",
}
function tierTip(c: GradeCell): string {
  const parts = [TIER_TIP[c.tier]]
  if (c.dida && !c.dida.reliable) parts.push(`内部样本仅 ${c.dida.count} 人`)
  return parts.join("；")
}

function gapCls(c: GradeCell): string {
  if (c.gap_pct == null) return "flat"
  if (Math.abs(c.gap_pct) < 0.05) return "flat"
  return c.gap_pct > 0 ? "up" : "down"
}
function gapTxt(c: GradeCell): string {
  if (c.gap_pct == null) return "—"
  return (c.gap_pct > 0 ? "+" : "") + (c.gap_pct * 100).toFixed(1) + "%"
}

function toggleCity(c: string) {
  const all = matrix.value?.cities ?? []
  const i = cityFilter.value.indexOf(c)
  if (i >= 0) cityFilter.value.splice(i, 1)
  else cityFilter.value.push(c)
  // 清空时视为"全部"
  if (!cityFilter.value.length) cityFilter.value = all.slice()
}
function barWidth(c: GradeCell): string {
  if (c.gap_pct == null) return "0%"
  return Math.min(100, Math.abs(c.gap_pct) * 100 * 3) + "%"
}

async function loadMatrix() {
  if (!selected.value) return
  loading.value = true
  try {
    matrix.value = await api.benchmarkByGrade({
      position: selected.value,
      city: cityFilter.value.join(",") || undefined,
    })
  } catch (e) {
    ElMessage.error("加载失败: " + (e as Error).message)
  } finally {
    loading.value = false
  }
}

async function openDrill(grade: GradeMeta, ct: string) {
  const c = cell(grade.code, ct)
  drillTitle.value = `${selected.value} · ${ct} · ${grade.code} ${grade.title}`
  drillSub.value = [
    `DIDA P50 ${wan(c?.dida?.p50)} 万（${c?.dida?.count ?? 0} 人）`,
    `市场参照 P50 ${wan(c?.market_ref?.p50)} 万（tier${c?.tier ?? "-"}）`,
  ].join(" · ")
  try {
    drillRows.value = await api.records({
      position: selected.value,
      level: grade.market_level ?? undefined,
      city: ct === "全国" ? undefined : ct,
      limit: 50,
    })
  } catch (e) {
    ElMessage.error("穿透失败: " + (e as Error).message)
  }
  drawer.value = true
}

onMounted(async () => {
  const [ps, gs] = await Promise.all([api.positions(), api.grades()])
  positions.value = ps
  grades.value = gs
  const qp = route.query.position as string | undefined
  if (qp && ps.some(p => p.position === qp)) selected.value = qp
  else if (ps.length) selected.value = ps[0].position
})
watch(selected, v => { router.replace({ query: v ? { position: v } : {} }) })
watch([selected, cityFilter], loadMatrix, { deep: true })
</script>

<template>
  <div>
    <div class="page-head">
      <h1>岗位对标</h1>
      <p>选岗位 → 按 DIDA 职级（P0–P8 / O1–O4 / M4–M5）看级别 × 城市矩阵。每格市场 P50 vs DIDA P50，点格穿透证据链。</p>
    </div>

    <div class="pos-hero">
      <div>
        <div class="ttl">{{ selected || "选择岗位" }}</div>
        <div class="desc">
          覆盖 {{ cities.length }} 城市 · {{ visibleGrades.length }} 个 DIDA 职级
          <span v-if="matrix"> · 市场样本 {{ matrix.market ? Object.values(matrix.market).reduce((s,c)=>s+Object.values(c).reduce((x,y)=>x+y.count,0),0) : 0 }} 条</span>
        </div>
      </div>
      <div class="hero-stats">
        <div v-if="matrix" class="stat">
          <div class="l">当前岗位 DIDA 在册</div>
          <div class="v num">{{ grades.filter(g => matrix?.dida[g.code] && Object.keys(matrix.dida[g.code]).length).length }} 档有数据</div>
        </div>
      </div>
    </div>

    <div class="chip-row">
      <span class="chip-label">序列：</span>
      <span class="chip" :class="{on: seqFilter==='P'}" @click="seqFilter='P'">P 序列</span>
      <span class="chip" :class="{on: seqFilter==='O'}" @click="seqFilter='O'">O 序列</span>
      <span class="chip" :class="{on: seqFilter==='M'}" @click="seqFilter='M'">M 序列</span>
      <span class="chip" :class="{on: seqFilter==='all'}" @click="seqFilter='all'">全部</span>
    </div>

    <div class="chip-row">
      <span class="chip-label">岗位：</span>
      <el-select v-model="selected" filterable placeholder="搜索岗位" style="width: 320px; margin-right: 12px">
        <el-option v-for="p in positions" :key="p.position" :value="p.position"
          :label="`${p.position}（${p.count}条）`" />
      </el-select>
      <span class="chip-label">城市：</span>
      <span class="chip on" @click="cityFilter = (matrix?.cities ?? []).slice()">全部</span>
      <span v-for="c in matrix?.cities ?? []" :key="c"
        class="chip" :class="{on: !cityFilter.length || cityFilter.includes(c)}"
        @click="toggleCity(c)">{{ c }}</span>
    </div>

    <div class="card" v-loading="loading">
      <div class="card-head">
        <h3>DIDA 职级 × 城市 薪酬矩阵（万元/年）</h3>
        <span class="hint">①职级×城市直对标 ②全国职级对标 ③市场级别带参照 · 灰=样本&lt;5 · 红=高于市场 · 绿=低于市场</span>
      </div>
      <div class="card-body matrix-wrap" v-if="matrix">
        <table class="matrix">
          <thead>
            <tr>
              <th>DIDA 职级 ＼ 城市</th>
              <th v-for="ct in cities" :key="ct">{{ ct }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="g in visibleGrades" :key="g.code">
              <th class="rowhead">
                <div class="g-code">{{ g.code }} · {{ g.title }}</div>
                <div class="g-meta">DIDA 在册 {{ g.count }} 人</div>
              </th>
              <td v-for="ct in cities" :key="ct" class="cell"
                :class="{empty: !hasData(cell(g.code, ct)), tier3: cell(g.code, ct)?.tier === 3}"
                @click="openDrill(g, ct)">
                <template v-if="hasData(cell(g.code, ct))">
                  <div class="row1">
                    <span class="tier-badge" :title="tierTip(cell(g.code, ct)!)">{{ cell(g.code, ct)!.tier }}</span>
                    <span class="gap" :class="gapCls(cell(g.code, ct)!)">{{ gapTxt(cell(g.code, ct)!) }}</span>
                  </div>
                  <div class="dida">
                    <template v-if="cell(g.code, ct)!.dida">
                      DIDA P50 <b :class="{low: !cell(g.code, ct)!.dida!.reliable}">{{ wan(cell(g.code, ct)!.dida!.p50) }}</b> 万
                      <span v-if="!cell(g.code, ct)!.dida!.reliable" class="low-tag">n{{ cell(g.code, ct)!.dida!.count }}</span>
                    </template>
                    <template v-else>内部无数据</template>
                  </div>
                  <div class="mkt" v-if="cell(g.code, ct)!.market_ref">
                    市场 P50 <b>{{ wan(cell(g.code, ct)!.market_ref!.p50) }}</b> 万
                  </div>
                  <div class="mkt dim" v-else>市场无参照</div>
                  <div class="bar"><i :class="gapCls(cell(g.code, ct)!)" :style="{width: barWidth(cell(g.code, ct)!)}"></i></div>
                </template>
                <template v-else>无数据</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="card-body" v-else>
        <el-empty description="选择岗位后展示 DIDA 职级 × 城市 对标矩阵" />
      </div>
    </div>

    <!-- 全国 base 参考线（来自上传的薪酬报告，方案 B：不参与 gap 计算） -->
    <div class="card" v-if="matrix && matrix.national_reference && Object.keys(matrix.national_reference.by_grade).length">
      <div class="card-head">
        <h3>全国 base 参考线（薪酬报告）</h3>
        <span class="hint">来源：{{ matrix.national_reference.labels.join(' · ') }} · 基本薪资，不含奖金/股票 · 不参与上方差距计算</span>
      </div>
      <div class="card-body">
        <table class="ref-table">
          <thead>
            <tr><th>DIDA 职级</th><th>报告 P25</th><th>报告 P50</th><th>报告 P75</th><th>样本</th></tr>
          </thead>
          <tbody>
            <template v-for="g in visibleGrades" :key="g.code">
            <tr v-if="matrix.national_reference.by_grade[g.code]">
              <td class="g-cell">{{ g.code }} · {{ g.title }}</td>
              <td class="num">{{ wan(matrix.national_reference.by_grade[g.code].p25) }} 万</td>
              <td class="num strong">{{ wan(matrix.national_reference.by_grade[g.code].p50) }} 万</td>
              <td class="num">{{ wan(matrix.national_reference.by_grade[g.code].p75) }} 万</td>
              <td>{{ matrix.national_reference.by_grade[g.code].count }}</td>
            </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <el-drawer v-model="drawer" :title="drillTitle" size="520px">
      <div style="font-size:12.5px;color:var(--text-3);margin-bottom:12px">{{ drillSub }}</div>
      <el-table :data="drillRows" size="small" stripe>
        <el-table-column prop="company_name" label="来源" width="140" show-overflow-tooltip />
        <el-table-column prop="salary_range" label="月薪区间" width="130" />
        <el-table-column label="年薪CNY" width="100">
          <template #default="{ row }">{{ row.annual_cny ? wan(row.annual_cny)+'万' : '-' }}</template>
        </el-table-column>
        <el-table-column prop="source" label="渠道" width="130" />
        <el-table-column label="证据">
          <template #default="{ row }">
            <a v-if="row.source_url" :href="row.source_url" target="_blank" rel="noopener">原文</a>
            <span v-else style="color:#8A94A3">CSV</span>
          </template>
        </el-table-column>
      </el-table>
      <p style="font-size:12px;color:var(--text-3);margin-top:10px">
        * 区间中点待分布加权（PRD #2），数字仅供方向参考。
      </p>
    </el-drawer>
  </div>
</template>

<style scoped>
.pos-hero {
  background: linear-gradient(135deg, #0E7C7B 0%, #0A5F5E 100%);
  color: #fff; border-radius: var(--radius); padding: 20px 24px;
  margin-bottom: 16px; display: flex; align-items: center; gap: 24px;
}
.pos-hero .ttl { font-size: 20px; font-weight: 650; }
.pos-hero .desc { font-size: 13px; opacity: 0.85; margin-top: 4px; }
.hero-stats { margin-left: auto; display: flex; gap: 28px; }
.hero-stats .l { font-size: 11.5px; opacity: 0.8; }
.hero-stats .v { font-size: 20px; font-weight: 600; margin-top: 2px; }

.chip {
  padding: 5px 12px; border-radius: 999px; font-size: 12.5px;
  border: 1px solid var(--border-strong); background: #fff; color: var(--text-2);
  cursor: pointer; user-select: none;
}
.chip:hover { border-color: var(--brand); color: var(--brand); }
.chip.on { background: var(--brand); border-color: var(--brand); color: #fff; }

.matrix-wrap { overflow-x: auto; }
table.matrix { border-collapse: separate; border-spacing: 0; width: 100%; font-size: 12.5px; }
table.matrix th, table.matrix td {
  border-right: 1px solid var(--border); border-bottom: 1px solid var(--border);
  padding: 0; text-align: center;
}
table.matrix thead th {
  background: var(--surface-2); font-weight: 600; color: var(--text-2);
  padding: 10px 8px; position: sticky; top: 0;
}
table.matrix .rowhead {
  background: var(--surface-2); padding: 10px 14px; text-align: left; white-space: nowrap;
  position: sticky; left: 0;
}
.g-code { font-weight: 600; color: var(--text); }
.g-meta { font-weight: 400; font-size: 11px; color: var(--text-3); margin-top: 2px; }
table.matrix td.cell {
  height: 76px; cursor: pointer; padding: 8px 10px; min-width: 140px;
  transition: background 0.12s;
}
table.matrix td.cell:hover { outline: 2px solid var(--brand); outline-offset: -2px; }
table.matrix td.cell.empty {
  background: repeating-linear-gradient(45deg, #FAFBFC, #FAFBFC 6px, #F2F3F5 6px, #F2F3F5 12px);
  color: var(--text-3);
}
.cell .row1 { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 4px; }
.cell .tier-badge {
  font-size: 10.5px; font-weight: 700; width: 16px; height: 16px; line-height: 16px;
  border-radius: 50%; background: var(--brand); color: #fff; text-align: center;
  cursor: help; flex-shrink: 0;
}
.cell.tier3 .tier-badge { background: var(--border-strong); color: var(--text-2); }
.cell.tier3 .dida b.low { color: var(--text-3); }
.cell .low-tag {
  font-size: 10px; color: var(--text-3); border: 1px solid var(--border-strong);
  border-radius: 3px; padding: 0 3px; margin-left: 2px;
}
.cell .mkt { font-size: 11.5px; color: var(--text-3); }
.cell .mkt.dim { color: var(--text-3); opacity: 0.7; }
.cell .mkt b { color: var(--text); font-size: 13.5px; font-weight: 600; }
.cell .gap { font-size: 11.5px; font-weight: 600; padding: 1px 6px; border-radius: 4px; }
.gap.up { color: var(--warn); background: var(--warn-soft); }
.gap.down { color: var(--good); background: var(--good-soft); }
.gap.flat { color: var(--text-3); background: var(--neutral-soft); }
.cell .dida { font-size: 11.5px; color: var(--text-2); }
.cell .dida b { color: var(--brand-deep); font-size: 13px; }
.cell .bar { height: 3px; background: var(--border); border-radius: 2px; margin-top: 6px; overflow: hidden; }
.cell .bar > i { display: block; height: 100%; background: var(--brand); }
.cell .bar > i.up { background: var(--warn); }
.cell .bar > i.down { background: var(--good); }

.ref-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.ref-table th, .ref-table td {
  border-bottom: 1px solid var(--border); padding: 8px 12px; text-align: left;
}
.ref-table th { color: var(--text-3); font-weight: 500; font-size: 12px; }
.ref-table td.g-cell { font-weight: 600; }
.ref-table td.num.strong { color: var(--brand-deep); font-weight: 600; font-size: 14px; }
.ref-table tbody tr:hover { background: var(--surface-2); }
</style>
