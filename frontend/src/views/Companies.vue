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
      </el-table>
    </el-card>
  </div>
</template>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.name-link { color: #409eff; text-decoration: none; }
.name-link:hover { text-decoration: underline; }
</style>
