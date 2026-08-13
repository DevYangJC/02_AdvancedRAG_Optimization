/**
 * 认证状态:token 持久化到 localStorage,登录/登出/改密。
 * 本 store 是 token 的唯一管理者;api/client 拦截器也从 localStorage 读同一份,
 * 保证"刷新 token 后重放请求"与这里的内存状态始终一致。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { authApi } from '@/api/auth'
import type { User } from '@/types/api'

// 从 localStorage 恢复用户信息:页面刷新后 store 重建时同步恢复登录态。
// try/catch 防脏数据:localStorage 里的 user 若被破坏,解析失败就当未登录处理。
function loadUser(): User | null {
  try {
    const raw = localStorage.getItem('user')
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

// Pinia 的 setup 写法:状态与动作都定义在闭包里,return 出去的部分才是对外 API。
export const useAuthStore = defineStore('auth', () => {
  // 两个响应式状态:user 驱动界面上的昵称/角色,token 驱动鉴权与路由守卫。
  const user = ref<User | null>(loadUser())
  // token 直接读 localStorage:刷新后自动恢复,无需等待任何异步操作。
  const token = ref<string | null>(localStorage.getItem('access_token'))

  // 登录/注册共用的落盘逻辑:同时写入内存与 localStorage,
  // 保证刷新不丢登录态;refresh_token 一并保存,供 401 拦截器续期使用。
  function persist(resp: { access_token: string; refresh_token: string; user: User }) {
    token.value = resp.access_token
    user.value = resp.user
    localStorage.setItem('access_token', resp.access_token)
    localStorage.setItem('refresh_token', resp.refresh_token)
    localStorage.setItem('user', JSON.stringify(resp.user))
  }

  // 登录与注册只是接口路径不同,成功后的处理完全一致(见 persist)。
  async function login(username: string, password: string) {
    const { data } = await authApi.login(username, password)
    persist(data)
  }

  // 注册成功即返回 token:前端"注册即登录",无需再跳登录页重复输入。
  async function register(username: string, password: string, nickname?: string) {
    const { data } = await authApi.register(username, password, nickname)
    persist(data)
  }

  // 改密由服务端作废旧 token:调用方(ChatView)成功后主动 logout 并跳登录页。
  async function changePassword(oldPassword: string, newPassword: string) {
    await authApi.changePassword(oldPassword, newPassword)
  }

  function logout() {
    // 登出即清空全部本地凭据:包括 refresh_token,一旦退出就无法再续期。
    user.value = null
    token.value = null
    localStorage.clear()
  }

  // 角色判断集中在这一处:所有"是否展示管理员入口"的判断都走它,避免各处写死。
  const isAdmin = () => user.value?.role === 'admin'

  return { user, token, login, register, changePassword, logout, isAdmin }
})
