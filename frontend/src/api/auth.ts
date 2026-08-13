/**
 * 认证相关 API:登录 / 注册 / 获取当前用户 / 修改密码。
 * 登录与注册接口直接返回 token 对,由调用方(store)负责持久化到 localStorage。
 */
import client from './client'
import type { TokenResponse, User } from '@/types/api'

export const authApi = {
  login(username: string, password: string) {
    return client.post<TokenResponse>('/auth/login', { username, password })
  },
  // 注册成功即返回 token:"注册即登录",前端无需再走一次 login。
  register(username: string, password: string, nickname?: string) {
    return client.post<TokenResponse>('/auth/register', { username, password, nickname })
  },
  // 页面刷新后恢复登录态用:校验 token 仍有效并回读最新用户信息。
  me() {
    return client.get<User>('/auth/me')
  },
  // 改密后旧密码立即失效、旧 token 作废,前端应提示用户重新登录。
  changePassword(old_password: string, new_password: string) {
    return client.put('/auth/password', { old_password, new_password })
  },
}
