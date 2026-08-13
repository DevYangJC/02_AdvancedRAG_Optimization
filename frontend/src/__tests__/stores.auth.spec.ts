/** auth store 单元测试:登录/注册/登出/权限判断/localStorage 持久化 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

// mock 掉 API 层,不触真实网络
vi.mock('@/api/auth', () => ({
  authApi: {
    login: vi.fn(),
    register: vi.fn(),
    changePassword: vi.fn(),
  },
}))

import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'

const userAdmin = { id: 'u1', username: 'admin', nickname: '管理员', role: 'admin', created_at: '' }
const userNormal = { id: 'u2', username: 'xiaowang', nickname: null, role: 'user', created_at: '' }

function tokenResp(user: any) {
  return { data: { access_token: 'access-1', refresh_token: 'refresh-1', token_type: 'bearer', user } }
}

beforeEach(() => {
  setActivePinia(createPinia())
  localStorage.clear()
  vi.clearAllMocks()
})

describe('auth store', () => {
  it('登录成功:持久化 token 与用户信息', async () => {
    ;(authApi.login as ReturnType<typeof vi.fn>).mockResolvedValue(tokenResp(userNormal))
    const store = useAuthStore()
    await store.login('xiaowang', 'pass123456')

    expect(authApi.login).toHaveBeenCalledWith('xiaowang', 'pass123456')
    expect(store.token).toBe('access-1')
    expect(store.user?.username).toBe('xiaowang')
    expect(localStorage.getItem('access_token')).toBe('access-1')
    expect(localStorage.getItem('refresh_token')).toBe('refresh-1')
  })

  it('注册成功:直接登录(注册即登录的约定)', async () => {
    ;(authApi.register as ReturnType<typeof vi.fn>).mockResolvedValue(tokenResp(userNormal))
    const store = useAuthStore()
    await store.register('xiaowang', 'pass123456', '小王')
    expect(authApi.register).toHaveBeenCalledWith('xiaowang', 'pass123456', '小王')
    expect(store.token).toBeTruthy()
  })

  it('登出:清空内存状态与 localStorage', async () => {
    localStorage.setItem('access_token', 't1')
    localStorage.setItem('refresh_token', 't2')
    localStorage.setItem('user', JSON.stringify(userNormal))
    const store = useAuthStore()
    expect(store.token).toBe('t1') // 从 localStorage 恢复

    store.logout()
    expect(store.token).toBeNull()
    expect(store.user).toBeNull()
    expect(localStorage.getItem('access_token')).toBeNull()
  })

  it('isAdmin:管理员为 true,普通用户为 false', () => {
    const store = useAuthStore()
    store.user = userAdmin as never // store 状态在内存,直接赋值(Pinia setup store 可写)
    expect(store.isAdmin()).toBe(true)

    store.user = userNormal as never
    expect(store.isAdmin()).toBe(false)
  })

  it('user 为 null 时 isAdmin 返回 false(未登录)', () => {
    const store = useAuthStore()
    expect(store.isAdmin()).toBe(false)
  })

  it('修改密码:调用 API 并透传参数', async () => {
    ;(authApi.changePassword as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { ok: true } })
    const store = useAuthStore()
    await store.changePassword('old123', 'new456')
    expect(authApi.changePassword).toHaveBeenCalledWith('old123', 'new456')
  })

  it('localStorage 中损坏的 user JSON 不导致崩溃', () => {
    localStorage.setItem('user', '{broken json')
    const store = useAuthStore()
    expect(store.user).toBeNull()
  })
})
