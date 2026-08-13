/**
 * 与后端契约的类型定义:字段名与 FastAPI 序列化输出一一对应,改动需前后端同步。
 * 类型只描述形状、不做运行时校验,字段拼错会在编译期暴露。
 */

// 用户:role 只有 admin / user 两档,前端所有权限判断都依赖它。
// nickname 可能为 null,展示用户名时要用 ?? 兜底到 username。
export interface User {
  id: string
  username: string
  nickname: string | null
  role: 'admin' | 'user'
  created_at: string
}

// 登录/注册的响应:一次性返回 access + refresh 两个 token,前端同时落盘。
// token_type 固定为 "bearer",前端无需判断,保留以兼容标准协议。
export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  user: User
}

// 会话:updated_at 是侧栏排序与时间展示的依据,由后端维护。
// title 会在首次问答后由后端自动生成(未生成前是"新对话")。
export interface Conversation {
  id: string
  title: string
  created_at: string
  updated_at: string
}

// 引用来源:回答中的 [n] 编号对应 index 字段,是前后端引用机制的唯一纽带。
// score 是向量相似度(0~1),界面展示时转为百分比。
export interface SourceRef {
  index: number
  doc_id: string
  doc_title: string
  page: number | null
  section: string | null
  snippet: string
  score: number
}

// 消息:status 驱动前端渲染(streaming 显光标、error 显中断提示),
// feedback 为 1(赞)/ -1(踩)/ null(未评)。
// 前端临时消息(id 以 local- 开头)也复用此结构,status 同样有效。
export interface Message {
  id: string
  conversation_id: string
  role: 'user' | 'assistant'
  content: string
  sources: SourceRef[] | null
  status: string
  feedback: number | null
  token_count: number | null
  created_at: string
}

// 文档:status 是入库流程的状态机,chunk_total/chunk_processed 供进度条使用。
// chunk_processed 仅在 processing 阶段递增,用于计算进度百分比。
export interface DocumentItem {
  id: string
  filename: string
  file_type: string
  size_bytes: number | null
  status: 'processing' | 'ready' | 'failed' | 'deleting'
  chunk_total: number
  chunk_processed: number
  error: string | null
  created_at: string
}

// 切分预览用的知识块:content 是切分后的原文,section/page 是定位信息。
// 预览页按 chunk_index 升序展示,顺序即原文顺序。
export interface ChunkItem {
  id: string
  chunk_index: number
  content: string
  page: number | null
  section: string | null
  token_count: number | null
}

// 管理页统计:cache_hit_rate 是 0~1 的小数,前端展示时需乘 100 转百分比。
// vector_count 与 chunk_count 应相等,不一致说明入库有遗漏(e2e 测试有对应断言)。
export interface AdminStats {
  document_count: number
  chunk_count: number
  vector_count: number
  total_question_count: number
  cache_hit_count: number
  cache_hit_rate: number
  user_count: number
  conversation_count: number
}

// 分页包装:所有列表接口统一返回该结构,泛型 T 是列表元素类型。
// total 供分页组件计算总页数;page 从 1 开始计数。
export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

/** SSE 事件:与 useSSE.ts 的协议帧一一对应 */
// data 的结构随 type 变化,用 any 表示,具体字段由调用方按帧类型解析。
export interface SSEEvent {
  type: 'meta' | 'delta' | 'done' | 'error'
  data: any
}
