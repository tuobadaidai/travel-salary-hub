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

export const api = {
  http,
  meta: () => http.get<Meta>("/meta").then(r => r.data),
  quantiles: (params: Record<string, unknown>) =>
    http.get<QuantileItem[]>("/stats/quantiles", { params }).then(r => r.data),
  trend: (params: Record<string, unknown>) =>
    http.get<Record<string, unknown>[]>("/stats/trend", { params }).then(r => r.data),
  companies: (params: Record<string, unknown>) =>
    http.get<CompanyItem[]>("/companies", { params }).then(r => r.data),
}
