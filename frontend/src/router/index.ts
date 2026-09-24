import { createRouter, createWebHistory } from "vue-router"

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", redirect: "/benchmark" },
    { path: "/benchmark", name: "benchmark", component: () => import("../views/Benchmark.vue") },
    { path: "/overseas", name: "overseas", component: () => import("../views/Overseas.vue") },
    { path: "/dashboard", name: "dashboard", component: () => import("../views/Dashboard.vue") },
    { path: "/companies", name: "companies", component: () => import("../views/Companies.vue") },
    { path: "/companies/:id", name: "companyDetail", component: () => import("../views/CompanyDetail.vue") },
    { path: "/data", name: "dataMaintenance", component: () => import("../views/DataMaintenance.vue") },
  ],
})
