import { createRouter, createWebHistory } from "vue-router"

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/", name: "dashboard", component: () => import("../views/Dashboard.vue") },
    { path: "/benchmark", name: "benchmark", component: () => import("../views/Benchmark.vue") },
    { path: "/companies", name: "companies", component: () => import("../views/Companies.vue") },
    { path: "/companies/:id", name: "companyDetail", component: () => import("../views/CompanyDetail.vue") },
  ],
})
