<script setup lang="ts">
import { onMounted, ref } from "vue"
import { ElMessage } from "element-plus"
import type { UploadFile } from "element-plus"
import { api } from "../api/salary"

interface CollectRunItem {
  id: number
  source_name: string
  status: string
  started_at: string | null
  finished_at: string | null
  items_fetched: number | null
  items_new: number | null
  items_rejected: number | null
  error_message: string | null
}

const runs = ref<CollectRunItem[]>([])
const loading = ref(false)
const uploading = ref(false)

const sourceLabel: Record<string, string> = {
  jobui_batch: "jobui 城市聚合采集",
  jobui_companies: "jobui 公司子页采集",
  overseas_snippet: "海外搜索摘要采集",
  overseas_clean: "海外数据清洗",
  dida_payroll_import: "DIDA 薪酬表导入",
  manual_csv: "历史 CSV 导入",
  reports_csv: "财报 CSV 导入",
  annual_report_crawl: "年报人力成本采集",
}

const statusType: Record<string, string> = {
  success: "success", running: "warning", partial: "warning", failed: "danger",
}

async function load() {
  loading.value = true
  try {
    runs.value = await api.http.get("/admin/collect-runs?limit=50").then(r => r.data)
  } finally {
    loading.value = false
  }
}

async function onUpload(file: UploadFile) {
  if (!file.raw) return false
  uploading.value = true
  const form = new FormData()
  form.append("file", file.raw)
  try {
    const r = await api.http.post("/admin/import/payroll", form, {
      headers: { "Content-Type": "multipart/form-data" },
    })
    const d = r.data as { added: number; skipped: number }
    ElMessage.success(`导入成功：新增 ${d.added} 条，跳过重复 ${d.skipped} 条`)
    await load()
  } catch (e) {
    const detail = (e as { response?: { data?: { detail?: string } } }).response?.data?.detail
    ElMessage.error("导入失败: " + (detail ?? (e as Error).message))
  } finally {
    uploading.value = false
  }
  return false
}

onMounted(load)
</script>

<template>
  <div class="maint">
    <el-card shadow="never">
      <template #header>DIDA 薪酬表上传（xlsx 匿名化导入）</template>
      <div class="upload-row">
        <el-upload
          drag
          accept=".xlsx"
          :show-file-list="false"
          :http-request="onUpload"
          :disabled="uploading"
        >
          <div class="up-inner">
            <el-icon class="up-icon" :size="36"><upload-filled /></el-icon>
            <div class="up-text">
              <b>{{ uploading ? "导入中…" : "拖拽或点击上传薪酬表 xlsx" }}</b>
              <div class="up-sub">
                需含列：职务 / 月度总和（CNY）/ 序列 / 职级 / 工作地点 · 重复行自动跳过 ·
                姓名/工号等个人标识不入库
              </div>
            </div>
          </div>
        </el-upload>
      </div>
      <p class="note">
        上传即匿名化导入对标基准库（dida_payroll），仅保留 职务/部门/序列/职级/月薪/地点 字段。
        同一文件重复上传不会产生重复数据。
      </p>
    </el-card>

    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>采集批次记录（最近 50 次）</span>
          <el-button text @click="load">刷新</el-button>
        </div>
      </template>
      <el-table :data="runs" v-loading="loading" stripe size="small">
        <el-table-column prop="id" label="#" width="60" />
        <el-table-column label="来源" min-width="160">
          <template #default="{ row }">{{ sourceLabel[row.source_name] ?? row.source_name }}</template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType[row.status] ?? 'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="items_new" label="新增" width="80" align="right" />
        <el-table-column prop="items_fetched" label="处理" width="80" align="right" />
        <el-table-column prop="started_at" label="开始时间" width="170" />
        <el-table-column prop="error_message" label="备注" show-overflow-tooltip />
      </el-table>
    </el-card>
  </div>
</template>

<script lang="ts">
import { UploadFilled } from "@element-plus/icons-vue"
export default { components: { UploadFilled } }
</script>

<style scoped>
.maint { display: flex; flex-direction: column; gap: 16px; }
.upload-row { display: flex; justify-content: center; }
.up-inner { padding: 20px 0; }
.up-text { margin-top: 4px; }
.up-sub { color: #909399; font-size: 12px; margin-top: 6px; }
.up-icon { color: #6a8df5; }
.note { color: #909399; font-size: 12px; margin: 12px 0 0; }
.head { display: flex; justify-content: space-between; align-items: center; }
</style>
