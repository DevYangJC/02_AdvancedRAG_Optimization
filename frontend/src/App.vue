<script setup lang="ts">
// 根组件:仅承载路由出口,登录态与权限拦截统一由路由守卫负责
</script>

<template>
  <!-- 路由出口:vue-router 按当前路径渲染对应页面,这里是全局唯一的挂载点 -->
  <router-view />
</template>
