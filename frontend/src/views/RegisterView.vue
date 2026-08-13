<script setup lang="ts">
/**
 * 注册页:前端空值校验 → 调用 auth store 注册 → 自动登录并跳转。
 */
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const form = ref({ username: '', nickname: '', password: '', confirm: '' })
const loading = ref(false)

async function onSubmit() {
  const { username, nickname, password, confirm } = form.value
  if (!username || !password) return ElMessage.warning('请输入用户名和密码')
  if (password.length < 6) return ElMessage.warning('密码至少 6 位')
  if (password !== confirm) return ElMessage.warning('两次密码不一致')

  loading.value = true
  try {
    await auth.register(username, password, nickname || undefined)
    ElMessage.success('注册成功，已为你自动登录')
    router.push('/chat')
  } catch {
    /* 错误由拦截器处理 */
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
        <h1 class="auth-title">创建新账号</h1>
        <p class="auth-subtitle">加入 RAG 智能知识库，体验高效检索问答</p>
      </div>

      <el-form @submit.prevent="onSubmit" size="large" class="auth-form">
        <el-form-item>
          <el-input
            v-model="form.username"
            placeholder="用户名（必填）"
            autocomplete="username"
            clearable
            prefix-icon="User"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.nickname"
            placeholder="昵称（选填）"
            clearable
            prefix-icon="UserFilled"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码（至少 6 位）"
            autocomplete="new-password"
            show-password
            prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="form.confirm"
            type="password"
            placeholder="确认密码"
            autocomplete="new-password"
            show-password
            prefix-icon="Lock"
            @keyup.enter="onSubmit"
          />
        </el-form-item>

        <el-button type="primary" class="auth-btn" :loading="loading" @click="onSubmit">
          注 册
        </el-button>
      </el-form>

      <div class="auth-links">
        <span>已有账号？</span>
        <router-link to="/login" class="link-text">直接登录</router-link>
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
  padding: 40px 38px;
  background: rgba(30, 41, 59, 0.7);
  backdrop-filter: blur(20px);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 20px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.4);
  z-index: 10;
}

.brand-badge {
  text-align: center;
  margin-bottom: 24px;
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
  padding: 6px 12px;
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
</style>
