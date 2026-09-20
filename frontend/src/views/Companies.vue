<script setup lang="ts">
import { onMounted, ref } from "vue"
import { api, type CompanyItem } from "../api/salary"

const list = ref<CompanyItem[]>([])
const typeFilter = ref<string | null>(null)
const loading = ref(false)

const typeLabel: Record<string, string> = {
  OTA: "OTA", B2B: "B2B",
  traditional_agency: "传统旅行社", other: "其他",
}

async function load() {
  loading.value = true
  try {
    list.value = await api.companies(typeFilter.value ? { company_type: typeFilter.value } : {})
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div>
    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>竞争公司名单（{{ list.length }}）</span>
          <el-select v-model="typeFilter" placeholder="类型" clearable style="width: 150px" @change="load">
            <el-option v-for="(l, k) in typeLabel" :key="k" :label="l" :value="k" />
          </el-select>
        </div>
      </template>
      <el-table :data="list" v-loading="loading" stripe>
        <el-table-column label="公司" min-width="160">
          <template #default="{ row }">
            <router-link :to="`/companies/${row.id}`" class="name-link">{{ row.name }}</router-link>
          </template>
        </el-table-column>
        <el-table-column prop="short_name" label="简称" width="110" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">{{ typeLabel[row.company_type] ?? row.company_type }}</template>
        </el-table-column>
        <el-table-column prop="hq_country" label="总部国家" width="90" />
        <el-table-column label="上市" width="70">
          <template #default="{ row }">
            <el-tag v-if="row.is_listed" type="success" size="small">已上市</el-tag>
            <el-tag v-else type="info" size="small">非上市</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="stock_code" label="股票代码" width="130" />
        <el-table-column prop="record_count" label="薪酬记录数" width="110" align="right" />
        <el-table-column label="人均人力成本/年" width="140" align="right">
          <template #default="{ row }">
            <span v-if="row.report?.avg_salary != null" :class="{ low: row.report.confidence !== 'high' }">
              {{ (row.report.avg_salary / 10000).toFixed(1) }}万
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="人均营收/年" width="120" align="right">
          <template #default="{ row }">
            <span v-if="row.report?.revenue != null && row.report?.employees">
              {{ (row.report.revenue / row.report.employees / 10000).toFixed(0) }}万
            </span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
        <el-table-column label="员工数" width="100" align="right">
          <template #default="{ row }">
            <span v-if="row.report?.employees">{{ row.report.employees.toLocaleString() }}</span>
            <span v-else class="dim">—</span>
          </template>
        </el-table-column>
      </el-table>
      <p class="eff-note">
        人效数据来源：A股公司年报 PDF（支付给职工现金 ÷ 期末员工数，现金口径含社保公积金）；
        港股公司为东财 F10 营收 ÷ 员工数（无薪酬总额披露）。人均人力成本列灰色表示中低置信度。
        人均营收受收入确认口径影响大（如旅行社净额法），跨公司对比仅供参考。
      </p>
    </el-card>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.name-link { color: #409eff; text-decoration: none; }
.name-link:hover { text-decoration: underline; }
.eff-note { color: #909399; font-size: 12px; margin: 10px 0 0; line-height: 1.6; }
.low { color: #909399; }
.dim { color: #c0c4cc; }
</style>
