import axios from "axios"

const http = axios.create({ baseURL: "http://localhost:8300/api/v1" })

export interface QuantileItem {
  group_key: string
  count: number
  p25: number
  p50: number
  p75: number
  p90: number
  reliable: boolean
}

export interface Meta {
  cities: string[]
  countries: string[]
  job_families: { id: number; code: string; name: string }[]
  company_types: string[]
  levels: string[]
  latest_collect_date: string | null
  total_records: number
}

export interface CompanyItem {
  id: number
  name: string
  short_name: string
  company_type: string
  hq_country: string
  stock_code: string | null
  is_listed: boolean
  record_count: number
}

export interface PositionItem {
  position: string
  count: number
  levels: string[]
}

export interface BenchCell {
  count: number
  p25: number
  p50: number
  p75: number
  p90: number
  reliable: boolean
}

export interface BenchmarkMatrix {
  position: string
  levels: string[]
  cities: string[]
  market: Record<string, Record<string, BenchCell>>
  dida: Record<string, Record<string, BenchCell>>
}

export interface HeatCell { p50: number; count: number; reliable: boolean }
export interface Heatmap {
  row_dim: string
  col_dim: string
  row_keys: string[]
  col_keys: string[]
  grid: (HeatCell | null)[][]
}

export interface DrillRecord {
  id: number
  position: string
  company_name: string
  city: string
  country: string
  currency: string
  salary_range: string | null
  annual_cny: number | null
  level: string | null
  source: string
  source_url: string | null
  collect_date: string
  sample_count: number | null
}

export interface GradeMeta {
  code: string
  title: string
  seq: "P" | "O" | "M"
  market_level: string | null
  count: number
}

export interface GradeBenchmark {
  position: string
  grades: GradeMeta[]
  cities: string[]
  market: Record<string, Record<string, QuantileItem>>
  dida: Record<string, Record<string, QuantileItem>>
}

export const DIMENSIONS = [
  { value: "job_family", label: "岗位族" },
  { value: "level", label: "级别" },
  { value: "city", label: "城市" },
  { value: "country", label: "国家" },
  { value: "company_type", label: "公司类型" },
  { value: "position", label: "岗位" },
]

export const api = {
  http,
  meta: () => http.get<Meta>("/meta").then(r => r.data),
  quantiles: (params: Record<string, unknown>) =>
    http.get<QuantileItem[]>("/stats/quantiles", { params }).then(r => r.data),
  trend: (params: Record<string, unknown>) =>
    http.get<Record<string, unknown>[]>("/stats/trend", { params }).then(r => r.data),
  companies: (params: Record<string, unknown>) =>
    http.get<CompanyItem[]>("/companies", { params }).then(r => r.data),
  positions: () => http.get<PositionItem[]>("/positions").then(r => r.data),
  benchmark: (params: { position: string; level?: string; city?: string }) =>
    http.get<BenchmarkMatrix>("/benchmark", { params }).then(r => r.data),
  grades: () => http.get<GradeMeta[]>("/grades").then(r => r.data),
  benchmarkByGrade: (params: { position: string; city?: string }) =>
    http.get<GradeBenchmark>("/benchmark-by-grade", { params }).then(r => r.data),
  heatmap: (params: { row_dim: string; col_dim: string }) =>
    http.get<Heatmap>("/stats/heatmap", { params }).then(r => r.data),
  records: (params: { position?: string; level?: string; city?: string; limit?: number }) =>
    http.get<DrillRecord[]>("/records", { params }).then(r => r.data),
}
