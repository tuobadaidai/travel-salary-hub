<script setup lang="ts">
</script>

<template>
  <el-container class="app">
    <el-header class="hd">
      <div class="brand">旅行行业薪酬看板</div>
      <el-menu mode="horizontal" router :default-active="$route.path" :ellipsis="false" class="menu">
        <el-menu-item index="/">总览</el-menu-item>
        <el-menu-item index="/benchmark">岗位对标</el-menu-item>
        <el-menu-item index="/companies">公司名单</el-menu-item>
        <el-menu-item index="/data">数据维护</el-menu-item>
      </el-menu>
    </el-header>
    <el-main>
      <router-view />
    </el-main>
  </el-container>
</template>

<style>
body { margin: 0; background: #f5f7fa; }
.app .hd { display: flex; align-items: center; gap: 24px; background: #fff; border-bottom: 1px solid #e4e7ed; }
.brand { font-size: 17px; font-weight: 600; white-space: nowrap; }
.menu { flex: 1; border-bottom: none !important; }
</style>
