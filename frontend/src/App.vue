<script setup lang="ts">
import { computed } from "vue"
import { useRoute } from "vue-router"
const route = useRoute()
const crumb = computed(() => {
  if (route.path.startsWith("/benchmark")) return { crumb: "岗位对标", sub: "按 DIDA 职级 apple-to-apple 对标" }
  if (route.path.startsWith("/overseas")) return { crumb: "海外驻地", sub: "F6 · 驻外员工薪酬与市场对照" }
  if (route.path.startsWith("/dashboard")) return { crumb: "总览", sub: "薪酬水位 vs 市场" }
  if (route.path.startsWith("/companies")) return { crumb: "竞争公司库", sub: "19 家 OTA / 旅行 B2B" }
  if (route.path.startsWith("/data")) return { crumb: "数据维护", sub: "采集批次与质量告警" }
  return { crumb: "", sub: "" }
})
</script>

<template>
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="logo-mark">薪</div>
        <div>
          <div class="brand-name">薪酬对标工作台</div>
          <div class="brand-sub">DIDA HR · 内部工具</div>
        </div>
      </div>
      <nav class="nav">
        <div class="nav-label">工作台</div>
        <router-link to="/benchmark" class="nav-item">
          <span class="dot"></span>岗位对标
        </router-link>
        <router-link to="/overseas" class="nav-item">
          <span class="dot"></span>海外驻地
        </router-link>
        <router-link to="/dashboard" class="nav-item">
          <span class="dot"></span>总览
        </router-link>
        <router-link to="/companies" class="nav-item">
          <span class="dot"></span>公司库
        </router-link>
        <div class="nav-label">系统</div>
        <router-link to="/data" class="nav-item">
          <span class="dot"></span>数据维护
        </router-link>
      </nav>
      <div class="sidebar-foot">
        <span class="live-dot"></span>数据更新于 2026-09-18<br />
        样本 532 条 · 19 家公司
      </div>
    </aside>

    <div class="main">
      <header class="topbar">
        <div class="crumbs">
          <span class="crumb-sub">{{ crumb.sub }}</span>
          <span class="crumb-sep">/</span>
          <b>{{ crumb.crumb }}</b>
        </div>
        <div class="top-right">
          <span class="badge-fresh">数据新鲜度 3 天</span>
        </div>
      </header>
      <main class="content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<style scoped>
.app-shell {
  display: grid;
  grid-template-columns: 232px 1fr;
  min-height: 100vh;
}
.sidebar {
  background: #1B2635;
  color: #C9D2DE;
  padding: 20px 0;
  display: flex;
  flex-direction: column;
  position: sticky;
  top: 0;
  height: 100vh;
}
.brand {
  padding: 0 22px 18px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  gap: 10px;
}
.logo-mark {
  width: 32px; height: 32px; border-radius: 8px;
  background: #0E7C7B; color: #fff;
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; font-size: 14px;
}
.brand-name { color: #fff; font-weight: 600; font-size: 15px; }
.brand-sub { color: #7E8A9C; font-size: 11.5px; margin-top: 2px; }

.nav { padding: 14px 12px; flex: 1; }
.nav-label { font-size: 11px; color: #6B7789; padding: 10px 12px 6px; letter-spacing: 0.6px; }
.nav-item {
  display: flex; align-items: center; gap: 10px;
  padding: 9px 12px; border-radius: 7px;
  color: #C9D2DE; cursor: pointer; font-size: 13.5px;
  margin-bottom: 2px; text-decoration: none;
}
.nav-item:hover { background: rgba(255,255,255,0.05); color: #fff; }
.nav-item.router-link-active { background: #0E7C7B; color: #fff; }
.nav-item .dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: currentColor; opacity: 0.6;
}
.nav-item.router-link-active .dot { opacity: 1; }

.sidebar-foot {
  padding: 14px 22px;
  border-top: 1px solid rgba(255,255,255,0.08);
  font-size: 11.5px; color: #7E8A9C; line-height: 1.7;
}
.live-dot {
  display: inline-block; width: 6px; height: 6px; border-radius: 50%;
  background: #34D399; margin-right: 6px; vertical-align: 1px;
}

.main { display: flex; flex-direction: column; min-width: 0; }
.topbar {
  background: #fff;
  border-bottom: 1px solid #E4E6EB;
  padding: 12px 28px;
  display: flex; align-items: center; gap: 16px;
  position: sticky; top: 0; z-index: 20;
}
.crumbs { font-size: 13px; color: #8A94A3; }
.crumb-sub { color: #8A94A3; }
.crumb-sep { margin: 0 8px; color: #CBD0D8; }
.crumbs b { color: #1B2330; font-weight: 600; }
.top-right { margin-left: auto; }
.badge-fresh {
  font-size: 12px; color: #15803D;
  background: #E2F3E7; padding: 4px 10px; border-radius: 999px;
}
.content { padding: 24px 28px 60px; min-width: 960px; }
</style>
