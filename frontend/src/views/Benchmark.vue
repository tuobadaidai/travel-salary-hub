<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue"
import { useRoute, useRouter } from "vue-router"
import { ElMessage } from "element-plus"
import {
  api, type BenchmarkMatrix, type BenchCell, type PositionItem, type DrillRecord,
} from "../api/salary"

const keyword = ref("")
const route = useRoute()
const router = useRouter()
const positions = ref<PositionItem[]>([])
const selected = ref<string>("")
const cityFilter = ref<string[]>([])
const matrix = ref<BenchmarkMatrix | null>(null)
const loading = ref(false)
const wan = (v: number) => `${(v / 10000).toFixed(1)}万`

// 穿透抽屉
const drawer = ref(false)
const drillTitle = ref("")
const drillSide = ref<"market" | "dida">("market")
const drillRows = ref<DrillRecord[]>([])

function cell(src: Record<string, Record<string, BenchCell>> | undefined, lv: string, ct: string): BenchCell | null {
  return src?.[lv]?.[ct] ?? null
}

const filteredPositions = computed(() => {
  const kw = keyword.value.trim()
  return kw ? positions.value.filter(p => p.position.includes(kw)) : positions.value.slice(0, 50)
})

const cities = computed(() => {
  const all = matrix.value?.cities ?? []
  return cityFilter.value.length ? all.filter(c => cityFilter.value.includes(c)) : all
})
const levels = computed(() => matrix.value?.levels ?? [])

// 市场单元格渲染：P50 主数字 + P25-P75 区间，不可靠置灰
function marketText(lv: string, ct: string): string {
  const c = cell(matrix.value?.market, lv, ct)
  if (!c) return "—"
  return `${wan(c.p50)}${c.reliable ? "" : "*"}`
}
function marketTitle(lv: string, ct: string): string {
  const c = cell(matrix.value?.market, lv, ct)
  if (!c) return "无市场数据"
  return `样本 ${c.count}${c.reliable ? "" : "（<5 仅供参考）"}\nP25 ${wan(c.p25)} | P50 ${wan(c.p50)}\nP75 ${wan(c.p75)} | P90 ${wan(c.p90)}`
}
function didaText(lv: string, ct: string): string {
  const c = cell(matrix.value?.dida, lv, ct)
  if (!c) return "—"
  return `${wan(c.p50)}${c.reliable ? "" : "*"}`
}
function didaTitle(lv: string, ct: string): string {
  const c = cell(matrix.value?.dida, lv, ct)
  if (!c) return "无内部数据"
  return `人数 ${c.count}\nP25 ${wan(c.p25)} | P50 ${wan(c.p50)}\nP75 ${wan(c.p75)} | P90 ${wan(c.p90)}`
}
// 差值 = 内部 P50 - 市场 P50，正=高于市场
function gapText(lv: string, ct: string): string {
  const m = cell(matrix.value?.market, lv, ct)
  const d = cell(matrix.value?.dida, lv, ct)
  if (!m || !d || !m.reliable) return "—"
  const diff = d.p50 - m.p50
  const pct = Math.round((diff / m.p50) * 100)
  return `${pct > 0 ? "+" : ""}${pct}%`
}
function gapClass(lv: string, ct: string): string {
  const m = cell(matrix.value?.market, lv, ct)
  const d = cell(matrix.value?.dida, lv, ct)
  if (!m || !d || !m.reliable) return ""
  const pct = (d.p50 - m.p50) / m.p50
  return pct >= 0.1 ? "gap-high" : pct <= -0.1 ? "gap-low" : "gap-mid"
}

async function loadMatrix() {
  if (!selected.value) return
  loading.value = true
  try {
    matrix.value = await api.benchmark({ position: selected.value, city: cityFilter.value.join(",") || undefined })
  } catch (e) {
    ElMessage.error("加载失败: " + (e as Error).message)
  } finally {
    loading.value = false
  }
}

// 点市场格 → 穿透市场明细；点 DIDA 格 → 穿透内部明细
async function openDrill(lv: string, ct: string, side: "market" | "dida") {
  const c = cell(matrix.value?.[side], lv, ct)
  if (!c) return
  drillTitle.value = `${matrix.value?.position} · ${lv} · ${ct}（${side === "market" ? "市场" : "DIDA 内部"}）`
  drillSide.value = side
  try {
    if (side === "market") {
      drillRows.value = await api.records({ position: selected.value, level: lv, city: ct, limit: 80 })
    } else {
      // DIDA 内部走 records 的 position 匹配不到（内部表独立），此处展示该格摘要信息
      drillRows.value = []
    }
  } catch (e) {
    ElMessage.error("穿透失败: " + (e as Error).message)
  }
  drawer.value = true
}

onMounted(async () => {
  positions.value = await api.positions()
  const qp = route.query.position as string | undefined
  if (qp && positions.value.some(p => p.position === qp)) selected.value = qp
})
watch(selected, loadMatrix)
watch(cityFilter, loadMatrix, { deep: true })
watch(selected, v => {
  router.replace({ query: v ? { position: v } : {} })
})
</script>

<template>
  <div class="bench">
    <el-card shadow="never" class="pick-card">
      <el-select
        v-model="selected" filterable remote :remote-method="(q: string) => (keyword = q)"
        placeholder="输入或选择岗位，如 客服专员 / 后端工程师 / 产品经理" style="width: 380px"
      >
        <el-option v-for="p in filteredPositions" :key="p.position" :value="p.position"
          :label="`${p.position}（${p.count}条）`" />
      </el-select>
      <el-select v-model="cityFilter" multiple collapse-tags placeholder="城市过滤（默认全部）" clearable style="width: 260px">
        <el-option v-for="c in matrix?.cities ?? []" :key="c" :label="c" :value="c" />
      </el-select>
      <span class="note">* = 样本不足5条，仅供参考；差距 = 内部P50 vs 市场P50</span>
    </el-card>

    <el-card v-if="matrix" v-loading="loading" shadow="never">
      <template #header>
        「{{ matrix.position }}」岗位对标矩阵 · 市场年薪 CNY（来源：jobui 聚合 / 历史 JD）vs DIDA 内部
      </template>
      <table class="matrix">
        <thead>
          <tr>
            <th class="corner">级别 \ 城市</th>
            <th v-for="ct in cities" :key="ct" colspan="3">{{ ct }}</th>
          </tr>
          <tr class="sub">
            <th class="corner"></th>
            <template v-for="ct in cities" :key="ct">
              <th>市场</th><th>DIDA</th><th>差距</th>
            </template>
          </tr>
        </thead>
        <tbody>
          <tr v-for="lv in levels" :key="lv">
            <th class="row-head">{{ lv }}</th>
            <template v-for="ct in cities" :key="ct">
              <td :title="marketTitle(lv, ct)" class="clickable"
                :class="{ thin: !cell(matrix.market, lv, ct)?.reliable }"
                @click="openDrill(lv, ct, 'market')">
                {{ marketText(lv, ct) }}
              </td>
              <td :title="didaTitle(lv, ct)" class="clickable dida" @click="openDrill(lv, ct, 'dida')">
                {{ didaText(lv, ct) }}
              </td>
              <td :class="gapClass(lv, ct)">{{ gapText(lv, ct) }}</td>
            </template>
          </tr>
        </tbody>
      </table>
    </el-card>
    <el-empty v-else description="选择岗位后展示 级别×城市 对标矩阵" />

    <el-drawer v-model="drawer" :title="drillTitle" size="52%">
      <template v-if="drillSide === 'market'">
        <el-table :data="drillRows" size="small" stripe>
          <el-table-column prop="company_name" label="来源" width="130" show-overflow-tooltip />
          <el-table-column prop="salary_range" label="月薪区间" width="120" />
          <el-table-column label="年薪CNY" width="100">
            <template #default="{ row }">{{ row.annual_cny ? wan(row.annual_cny) : "-" }}</template>
          </el-table-column>
          <el-table-column prop="source" label="渠道" width="120" />
          <el-table-column label="证据">
            <template #default="{ row }">
              <a v-if="row.source_url" :href="row.source_url" target="_blank" rel="noopener" class="ev-link">原文</a>
              <span v-else class="ev-none">CSV</span>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!drillRows.length" description="该格无逐条明细（聚合源数据仅保留分位汇总）" />
      </template>
      <template v-else>
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item
            v-for="ct in cities" :key="ct"
            :label="`${drillTitle.split('·')[1]?.trim() ?? ''} · ${ct}`">
            {{ didaText(drillTitle.split('·')[1]?.trim() ?? '', ct) }}
          </el-descriptions-item>
        </el-descriptions>
        <p class="dida-note">DIDA 内部数据来自薪酬表（匿名化），精确到职务×职级×地点。明细穿透请看「内部对标」。</p>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.bench { display: flex; flex-direction: column; gap: 16px; }
.pick-card :deep(.el-card__body) { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.note { color: #909399; font-size: 12px; margin-left: auto; }
.matrix { border-collapse: collapse; width: 100%; }
.matrix th, .matrix td { border: 1px solid #e4e7ed; padding: 8px 10px; text-align: center; font-size: 13px; }
.matrix thead th { background: #f5f7fa; }
.matrix .corner { text-align: left; width: 90px; }
.matrix .row-head { background: #f5f7fa; }
.matrix td { min-width: 76px; cursor: default; }
.matrix td.clickable { cursor: pointer; }
.matrix td.clickable:hover { outline: 2px solid #3d6db3; outline-offset: -2px; }
.matrix td.dida { background: #fdf8f6; }
.matrix td.thin { color: #c0c4cc; }
.gap-high { color: #d25b4a; font-weight: 600; background: #fdf1ef; }
.gap-low { color: #4d9e60; font-weight: 600; background: #f0f9f2; }
.gap-mid { color: #909399; }
.ev-link { color: #3d6db3; }
.ev-none { color: #c0c4cc; font-size: 12px; }
.dida-note { color: #909399; font-size: 12px; margin-top: 12px; }
</style>
