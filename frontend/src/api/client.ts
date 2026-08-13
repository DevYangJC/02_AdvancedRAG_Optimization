/**
 * axios 二次封装:统一 baseURL 与公共拦截器。
 * 请求拦截器自动附带 JWT;响应拦截器遇 401 自动续期重放,其余错误统一提示。
 */
import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ElMessage } from 'element-plus'

// baseURL 统一 '/api' 前缀:开发期由 Vite proxy 转发到后端,生产期由 Nginx 反代。
const client = axios.create({
  baseURL: '/api',
  timeout: 30000, // 30 秒超时(SSE 流式请求不走 axios,不受此限制)
})

// 并发 401 的"单飞"刷新互斥:多个请求同时过期时,若各自调 /auth/refresh 会互相覆盖 token,
// 故用 refreshing 保存"进行中的刷新 Promise",后续请求复用同一个,保证只发一次刷新。
let refreshing: Promise<string | null> | null = null

/**
 * 用 refresh_token 换新 token 对:成功写入 localStorage 并返回新 access_token;
 * 失败(过期/被篡改)则清空登录态返回 null,由调用方跳转登录页。
 */
async function doRefresh(): Promise<string | null> {
  const refresh_token = localStorage.getItem('refresh_token')
  if (!refresh_token) return null
  try {
    // 注意:这里用裸 axios 而非 client,避免 refresh 请求自身
    // 陷入"401 → 再刷新"的循环(刷新接口失败也会返回 401)
    const { data } = await axios.post('/api/auth/refresh', { refresh_token })
    localStorage.setItem('access_token', data.access_token)
    localStorage.setItem('refresh_token', data.refresh_token)
    localStorage.setItem('user', JSON.stringify(data.user))
    return data.access_token
  } catch {
    // refresh_token 也失效(过期/被篡改)→ 登录态彻底失效
    localStorage.clear()
    return null
  }
}

// 请求拦截器:从 localStorage 读取 access_token 自动附带 Bearer 头,业务代码无需手动带。
client.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// 响应拦截器:401 自动续期重放 + 其余错误统一提示。
client.interceptors.response.use(
  // 成功响应原样返回:数据由调用方自行解构。
  (resp) => resp,
  // 失败响应集中处理:401 走续期,其余错误弹提示。
  async (error: AxiosError<{ message?: string; code?: string }>) => {
    const original = error.config as InternalAxiosRequestConfig & { _retried?: boolean }
    const status = error.response?.status

    // 401 条件过滤:请求配置存在(超时/断网无 config)、未重试过(防死循环)、
    // 且非认证接口自身(登录失败就是失败,无需刷新)。
    if (status === 401 && original && !original._retried && !original.url?.includes('/auth/')) {
      original._retried = true
      refreshing = refreshing ?? doRefresh() // 单飞:只发起一次刷新
      const token = await refreshing
      refreshing = null
      if (token) {
        // 换新 token 后重放原请求:用户完全无感知,无需重新登录。
        original.headers.Authorization = `Bearer ${token}`
        return client(original)
      }
      // 刷新失败:强制跳回登录页
      window.location.href = '/login'
      return Promise.reject(error)
    }

    // 其余错误统一弹出后端 message(错误体为 {code, message, detail});
    // SSE 流式问答由 useSSE.ts 用 fetch 单独处理,靠 headers.sse 标记跳过这里的提示。
    const msg = error.response?.data?.message || '网络请求失败,请稍后重试'
    if (!original?.headers?.sse) ElMessage.error(msg)
    return Promise.reject(error)
  },
)

export default client
