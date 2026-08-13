<script setup lang="ts">
/**
 * 登录页:前端空值校验 → 调用 auth store 登录 → 按原路径或角色跳转。
 */
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const form = ref({ username: '', password: '' })
const loading = ref(false)

async function onSubmit() {
  if (!form.value.username || !form.value.password) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await auth.login(form.value.username, form.value.password)
    ElMessage.success(`欢迎回来，${auth.user?.nickname || auth.user?.username}`)
    const redirect = (route.query.redirect as string) || (auth.isAdmin() ? '/admin/knowledge' : '/chat')
    router.push(redirect)
  } catch {
    /* 拦截器已处理 */
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <div class="bg-decoration-1"></div>
    <div class="bg-decoration-2"></div>

    <div class="auth-card">
      <div class="brand-badge">
        <div class="logo-box">
          <svg class="logo-svg" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path
              d="M12 2L2 7L12 12L22 7L12 2Z"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <path
              d="M2 17L12 22L22 17"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
            <path
              d="M2 12L12 17L22 12"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </div>
        <h1 class="auth-title">RAG 智能知识库</h1>
        <p class="auth-subtitle">企业级 LangChain 检索增强生成优化平台</p>
      </div>

      <el-form @submit.prevent="onSubmit" size="large" class="auth-form">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="用户名 / 账号"
            autocomplete="username"
            clearable
            prefix-icon="User"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            autocomplete="current-password"
            show-password
            prefix-icon="Lock"
            @keyup.enter="onSubmit"
          />
        </el-form-item>
        <el-button type="primary" class="auth-btn" :loading="loading" @click="onSubmit">
          登 录
        </el-button>
      </el-form>

      <div class="auth-links">
        <span>还没有账号？</span>
        <router-link to="/register" class="link-text">立即注册</router-link>
      </div>

      <div class="demo-tip">
        <span class="tip-badge">测试账号</span>
        <span>admin / 123456</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.auth-page {
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 50%, #0f172a 100%);
  position: relative;
  overflow: hidden;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
}

.bg-decoration-1 {
  position: absolute;
  width: 450px;
  height: 450px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.25) 0%, rgba(0, 0, 0, 0) 70%);
  top: -100px;
  left: -100px;
  pointer-events: none;
}

.bg-decoration-2 {
  position: absolute;
  width: 500px;
  height: 500px;
  border-radius: 50%;
  background: radial-gradient(circle, rgba(139, 92, 246, 0.2) 0%, rgba(0, 0, 0, 0) 70%);
  bottom: -150px;
  right: -100px;
  pointer-events: none;
}

.auth-card {
  width: 400px;
  padding: 44px 38px;
  background: rgba(30, 41, 59, 0.7);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 20px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4);
  z-index: 10;
}

.brand-badge {
  text-align: center;
  margin-bottom: 30px;
}

.logo-box {
  width: 48px;
  height: 48px;
  border-radius: 14px;
  background: linear-gradient(135deg, #6366f1 0%, #3b82f6 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 0 auto 14px;
  box-shadow: 0 6px 16px rgba(99, 102, 241, 0.4);
}

.logo-svg {
  width: 26px;
  height: 26px;
}

.auth-title {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: #f8fafc;
  letter-spacing: 0.5px;
}

.auth-subtitle {
  margin: 0;
  font-size: 12px;
  color: #94a3b8;
}

.auth-form :deep(.el-input__wrapper) {
  background: rgba(15, 23, 42, 0.6);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: none;
  border-radius: 10px;
  padding: 8px 12px;
}

.auth-form :deep(.el-input__inner) {
  color: #f8fafc;
}

.auth-btn {
  width: 100%;
  margin-top: 8px;
  border-radius: 10px;
  font-weight: 600;
  height: 44px;
  background: linear-gradient(135deg, #6366f1 0%, #4f46e5 100%);
  border: none;
  box-shadow: 0 6px 18px rgba(99, 102, 241, 0.35);
}

.auth-btn:hover {
  transform: translateY(-1px);
  box-shadow: 0 8px 22px rgba(99, 102, 241, 0.45);
}

.auth-links {
  margin-top: 20px;
  text-align: center;
  font-size: 13px;
  color: #94a3b8;
}

.link-text {
  color: #818cf8;
  font-weight: 600;
  text-decoration: none;
  margin-left: 4px;
}

.demo-tip {
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 12px;
  color: #64748b;
}

.tip-badge {
  background: rgba(99, 102, 241, 0.15);
  color: #a5b4fc;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
}
</style>
