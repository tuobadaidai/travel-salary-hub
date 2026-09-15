import { defineStore } from "pinia"
import { ref } from "vue"

export const useFilterStore = defineStore("filters", () => {
  const cities = ref<string[]>([])
  const country = ref<string | null>(null)
  const companyType = ref<string | null>(null)
  const jobFamilyId = ref<number | null>(null)
  const dateRange = ref<[string, string] | null>(null)

  function toParams(): Record<string, unknown> {
    const p: Record<string, unknown> = {}
    if (cities.value.length) p.city = cities.value.join(",")
    if (country.value) p.country = country.value
    if (companyType.value) p.company_type = companyType.value
    if (jobFamilyId.value) p.job_family_id = jobFamilyId.value
    if (dateRange.value) {
      p.date_from = dateRange.value[0]
      p.date_to = dateRange.value[1]
    }
    return p
  }

  function reset() {
    cities.value = []
    country.value = null
    companyType.value = null
    jobFamilyId.value = null
    dateRange.value = null
  }

  return { cities, country, companyType, jobFamilyId, dateRange, toParams, reset }
})
