/**
 * axios 二次封装测试:token 注入、401 自动刷新重放、单飞刷新、统一错误提示
 *
 * 用队列式自定义 adapter 模拟后端行为:
 *   队列元素为 'ok' | 'reject-401' | 'reject-400' | {status, data}
 *   adapter 收到的真实 config(含请求拦截器注入的 headers)会放进错误对象的 config,
 *   保证拦截器重放(return client(original))时拿到完整配置。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AxiosAdapter, InternalAxiosRequestConfig } from 'axios'

// mock Element Plus 提示组件(避免测试输出噪音),必须在 import client 前
vi.mock('element-plus', () => ({ ElMessage: { error: vi.fn(), warning: vi.fn() } }))

import axios from 'axios'
import client from '@/api/client'
import { ElMessage } from 'element-plus'

type AdapterBehavior = 'ok' | 'reject-401' | 'reject-400' | { status: number; data: unknown }
let behaviorQueue: AdapterBehavior[] = []

/** 安装队列式 adapter:按顺序消费行为,错误对象携带真实 config(与 axios 行为一致) */
function installQueueAdapter() {
  const queueAdapter: AxiosAdapter = (config: InternalAxiosRequestConfig) => {
    const behavior = behaviorQueue.shift() ?? 'ok'
    if (behavior === 'ok') {
      return Promise.resolve({ data: { ok: true }, status: 200, statusText: 'OK', headers: {}, config })
    }
    const status =
      typeof behavior === 'object' ? behavior.status : behavior === 'reject-401' ? 401 : 400
    const data = behavior === 'reject-400' ? { message: '用户名已存在' } : typeof behavior === 'object' ? behavior.data : {}
    return Promise.reject({ response: { status, data }, config })
  }
  client.defaults.adapter = queueAdapter
}

beforeEach(() => {
  localStorage.clear()
  behaviorQueue = []
  vi.clearAllMocks()
  installQueueAdapter()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe('请求拦截器:自动携带 Bearer token', () => {
  function captureAdapter() {
    // 用 vi.fn 捕获请求配置(TS 不跟踪闭包内赋值,故用 mock.calls 读取)
    const spy = vi.fn((config: InternalAxiosRequestConfig) =>
      Promise.resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config }),
    )
    client.defaults.adapter = spy as unknown as AxiosAdapter
    return spy
  }

  it('登录态存在时请求头带 token', async () => {
    localStorage.setItem('access_token', 'token-abc')
    const spy = captureAdapter()
    await client.get('/conversations')
    const captured = spy.mock.calls[0][0] as InternalAxiosRequestConfig
    expect(captured.headers.Authorization).toBe('Bearer token-abc')
  })

  it('未登录时不带 Authorization 头', async () => {
    const spy = captureAdapter()
    await client.get('/conversations')
    const captured = spy.mock.calls[0][0] as InternalAxiosRequestConfig
    expect(captured.headers.Authorization).toBeUndefined()
  })
})

describe('响应拦截器:401 自动刷新并重放', () => {
  it('access token 过期 → 刷新 → 用新 token 重放原请求', async () => {
    localStorage.setItem('access_token', 'expired-token')
    localStorage.setItem('refresh_token', 'refresh-1')
    vi.spyOn(axios, 'post').mockResolvedValue({
      data: { access_token: 'new-token', refresh_token: 'refresh-2', user: { id: 'u1', username: 'a' } },
    })
    behaviorQueue = ['reject-401', 'ok']

    const resp = await client.get('/conversations')

    expect(resp.data).toEqual({ ok: true }) // 重放成功,调用方无感知
    expect(axios.post).toHaveBeenCalledWith('/api/auth/refresh', { refresh_token: 'refresh-1' })
    expect(localStorage.getItem('access_token')).toBe('new-token')
  })

  it('并发 401 只触发一次刷新(单飞),多个请求都重放成功', async () => {
    localStorage.setItem('access_token', 'expired')
    localStorage.setItem('refresh_token', 'refresh-1')
    vi.spyOn(axios, 'post').mockResolvedValue({
      data: { access_token: 'new-token', refresh_token: 'refresh-2', user: { id: 'u1', username: 'a' } },
    })
    behaviorQueue = ['reject-401', 'reject-401', 'ok', 'ok']

    const [ra, rb] = await Promise.all([client.get('/a'), client.get('/b')])

    expect(ra.data).toEqual({ ok: true })
    expect(rb.data).toEqual({ ok: true })
    expect(axios.post).toHaveBeenCalledTimes(1) // 单飞:只刷新一次
  })

  it('无 refresh_token 时不发起刷新,错误原样抛出', async () => {
    localStorage.setItem('access_token', 'expired')
    behaviorQueue = ['reject-401']
    const postSpy = vi.spyOn(axios, 'post')

    await expect(client.get('/conversations')).rejects.toBeTruthy()
    expect(postSpy).not.toHaveBeenCalled()
  })

  it('认证接口本身的 401 不触发刷新(登录失败就是失败)', async () => {
    localStorage.setItem('access_token', 'some-token')
    localStorage.setItem('refresh_token', 'refresh-1')
    const postSpy = vi.spyOn(axios, 'post')
    behaviorQueue = [{ status: 401, data: { message: '用户名或密码错误' } }]

    await expect(client.post('/auth/login', { username: 'a', password: 'b' })).rejects.toBeTruthy()
    expect(postSpy).not.toHaveBeenCalled()
  })
})

describe('响应拦截器:统一错误提示', () => {
  it('非 401 错误弹出后端 message', async () => {
    behaviorQueue = ['reject-400']
    await expect(client.post('/auth/register', {})).rejects.toBeTruthy()
    expect(ElMessage.error).toHaveBeenCalledWith('用户名已存在')
  })

  it('sse 标记的请求不弹错误提示(由 useSSE 单独处理)', async () => {
    behaviorQueue = [{ status: 500, data: { message: '内部错误' } }]
    await expect(client.get('/x', { headers: { sse: true } })).rejects.toBeTruthy()
    expect(ElMessage.error).not.toHaveBeenCalled()
  })

  it('无后端 message 时给出兜底文案', async () => {
    behaviorQueue = [{ status: 502, data: {} }]
    await expect(client.get('/x')).rejects.toBeTruthy()
    expect(ElMessage.error).toHaveBeenCalledWith('网络请求失败,请稍后重试')
  })
})
