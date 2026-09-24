<script setup lang="ts">
import { computed, onMounted, ref } from "vue"
import { ElMessage } from "element-plus"
import { api, type OverseasData, type QuantileItem } from "../api/salary"

const titleFilter = ref("")
const data = ref<OverseasData | null>(null)
const loading = ref(false)
const expanded = ref<string | null>(null)

const LEVEL_ORDER = ["专员", "高级", "主管", "经理", "总监", "VP", "未知"]
const wan = (v: number | null | undefined) => v == null ? "—" : (v / 10000).toFixed(1)

const countries = computed(() => data.value?.internal.countries ?? [])
const sortedLevels = (by: Record<string, QuantileItem>) =>
  Object.keys(by).sort((a, b) => {
    const ia = LEVEL_ORDER.indexOf(a), ib = LEVEL_ORDER.indexOf(b)
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib)
  })
const curTxt = (curs: Record<string, number>) =>
  Object.entries(curs).sort((a, b) => b[1] - a[1]).map(([c, n]) => `${c}×${n}`).join(" ")

async function load() {
  loading.value = true
  try {
    data.value = await api.overseas({ title: titleFilter.value || undefined })
    if (countries.value.length) expanded.value = countries.value[0].country
  } catch (e) {
    ElMessage.error("加载失败: " + (e as Error).message)
  } finally {
    loading.value = false
  }
}
onMounted(load)
</script>

<template>
  <div>
    <div class="page-head">
      <h1>海外驻地</h1>
      <p>DIDA 海外驻地员工薪酬（CNY 折算，按国家 × 级别聚合）+ 市场海外记录对照（搜索摘要聚合，低置信）。</p>
    </div>

    <div class="hero-row">
      <div class="stat-card teal">
        <div class="l">海外驻地总人数</div>
        <div class="v">{{ data?.internal.total ?? "—" }}</div>
        <div class="s">覆盖 {{ countries.length }} 个国家/地区</div>
      </div>
      <div class="stat-card gray">
        <div class="l">市场海外记录</div>
        <div class="v">{{ data?.market.total ?? "—" }}</div>
        <div class="s">低置信 · 仅供方向参考</div>
      </div>
      <div class="filter-box">
        <el-input v-model="titleFilter" placeholder="按岗位关键词过滤，如 产品 / 销售" clearable
          style="width: 260px" @keyup.enter="load" @clear="load" />
        <el-button type="primary" @click="load">查询</el-button>
      </div>
    </div>

    <div class="country-grid" v-loading="loading">
      <div v-for="c in countries" :key="c.country" class="country-card"
        :class="{ open: expanded === c.country }" @click="expanded = expanded === c.country ? null : c.country">
        <div class="head">
          <div class="name">{{ c.country }}</div>
          <div class="meta">
            <span class="people">{{ c.count }} 人</span>
            <span class="cur">{{ curTxt(c.currencies) }}</span>
          </div>
        </div>
        <div class="level-strip">
          <div v-for="lv in sortedLevels(c.by_level)" :key="lv" class="lv-chip">
            <span class="lv">{{ lv }}</span>
            <span class="p50">{{ wan(c.by_level[lv].p50) }} 万</span>
            <span class="n" :class="{ low: !c.by_level[lv].reliable }">n{{ c.by_level[lv].count }}</span>
          </div>
        </div>
        <div class="detail" v-if="expanded === c.country">
          <table>
            <thead>
              <tr><th>级别</th><th>P25</th><th>P50</th><th>P75</th><th>P90</th><th>人数</th></tr>
            </thead>
            <tbody>
              <tr v-for="lv in sortedLevels(c.by_level)" :key="lv">
                <td class="lv-cell">{{ lv }}</td>
                <td class="num">{{ wan(c.by_level[lv].p25) }} 万</td>
                <td class="num strong">{{ wan(c.by_level[lv].p50) }} 万</td>
                <td class="num">{{ wan(c.by_level[lv].p75) }} 万</td>
                <td class="num">{{ wan(c.by_level[lv].p90) }} 万</td>
                <td :class="{ low: !c.by_level[lv].reliable }">{{ c.by_level[lv].count }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <el-empty v-if="!loading && !countries.length" description="无海外驻地数据" />
    </div>

    <div class="card" v-if="data && Object.keys(data.market.by_city).length">
      <div class="card-head">
        <h3>市场海外记录（城市聚合）</h3>
        <span class="hint">来源：搜索摘要聚合 · 低置信 · P50 为 CNY 折算年薪</span>
      </div>
      <div class="card-body market-strip">
        <div v-for="(q, ct) in data.market.by_city" :key="ct" class="m-chip">
          <div class="ct">{{ ct }}</div>
          <div class="p50">{{ wan(q.p50) }} 万</div>
          <div class="n">n{{ q.count }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.hero-row { display: flex; gap: 16px; margin-bottom: 20px; align-items: stretch; }
.stat-card {
  border-radius: var(--radius); padding: 18px 22px; min-width: 200px;
}
.stat-card.teal { background: linear-gradient(135deg, #0E7C7B 0%, #0A5F5E 100%); color: #fff; }
.stat-card.gray { background: var(--surface-2); color: var(--text-2); border: 1px solid var(--border); }
.stat-card .l { font-size: 12px; opacity: 0.8; }
.stat-card .v { font-size: 30px; font-weight: 700; margin-top: 4px; }
.stat-card .s { font-size: 11.5px; opacity: 0.75; margin-top: 2px; }
.filter-box { margin-left: auto; display: flex; gap: 8px; align-items: center; }

.country-grid { display: flex; flex-direction: column; gap: 12px; }
.country-card {
  background: #fff; border: 1px solid var(--border); border-radius: var(--radius);
  padding: 16px 20px; cursor: pointer; transition: box-shadow 0.15s;
}
.country-card:hover { box-shadow: 0 2px 10px rgba(14, 124, 123, 0.08); }
.country-card.open { border-color: var(--brand); }
.country-card .head { display: flex; align-items: baseline; gap: 14px; }
.country-card .name { font-size: 16px; font-weight: 650; color: var(--text); }
.country-card .meta { margin-left: auto; display: flex; gap: 12px; font-size: 12.5px; color: var(--text-3); }
.country-card .people { color: var(--brand-deep); font-weight: 600; }
.level-strip { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.lv-chip {
  display: inline-flex; align-items: baseline; gap: 6px;
  background: var(--surface-2); border: 1px solid var(--border);
  border-radius: 6px; padding: 5px 10px; font-size: 12px;
}
.lv-chip .lv { color: var(--text-2); }
.lv-chip .p50 { font-weight: 600; color: var(--brand-deep); }
.lv-chip .n { color: var(--text-3); font-size: 11px; }
.lv-chip .n.low { color: var(--warn); }
.detail { margin-top: 14px; border-top: 1px dashed var(--border); padding-top: 12px; }
.detail table { width: 100%; border-collapse: collapse; font-size: 13px; }
.detail th, .detail td { border-bottom: 1px solid var(--border); padding: 7px 10px; text-align: right; }
.detail th:first-child, .detail td:first-child { text-align: left; }
.detail th { color: var(--text-3); font-weight: 500; font-size: 12px; }
.detail .strong { color: var(--brand-deep); font-weight: 600; }
.detail .low { color: var(--text-3); }
.num.strong { color: var(--brand-deep); font-weight: 600; }

.market-strip { display: flex; flex-wrap: wrap; gap: 10px; }
.m-chip {
  border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px;
  font-size: 12px; min-width: 110px; text-align: center;
}
.m-chip .ct { color: var(--text-2); }
.m-chip .p50 { font-size: 15px; font-weight: 650; color: var(--brand-deep); margin: 2px 0; }
.m-chip .n { color: var(--text-3); font-size: 11px; }
</style>
