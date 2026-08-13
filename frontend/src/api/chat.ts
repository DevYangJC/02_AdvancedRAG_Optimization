/**
 * 会话与问答 API(不含 SSE 流式问答:流式由 useSSE.ts 用 fetch 单独实现)。
 * 覆盖会话 CRUD、历史消息分页与消息反馈。
 */
import client from './client'
import type { Conversation, Message, Paged } from '@/types/api'

export const chatApi = {
  // 侧栏会话列表:page 从 1 开始,page_size 默认 50 足够日常展示。
  listConversations(page = 1, page_size = 50) {
    return client.get<Paged<Conversation>>('/conversations', { params: { page, page_size } })
  },
  // 不传标题时后端会生成默认标题;返回带 id 的完整会话,前端据此跳转/渲染。
  createConversation(title?: string) {
    return client.post<Conversation>('/conversations', { title })
  },
  // 重命名仅改标题,不影响会话内容与历史消息。
  renameConversation(id: string, title: string) {
    return client.put<Conversation>(`/conversations/${id}`, { title })
  },
  // 删除不可恢复(后端级联清空消息与向量缓存),前端应有二次确认。
  deleteConversation(id: string) {
    return client.delete(`/conversations/${id}`)
  },
  // 历史消息带引用来源(sources):回看旧回答时引用标注依然可见。
  listMessages(conversationId: string, page = 1, page_size = 100) {
    return client.get<Paged<Message>>(`/conversations/${conversationId}/messages`, {
      params: { page, page_size },
    })
  },
  // value: 1 点赞 / -1 点踩,text 为补充说明;反馈数据用于统计答案质量。
  setFeedback(messageId: string, value: number, text?: string) {
    return client.post(`/conversations/messages/${messageId}/feedback`, { value, text })
  },
}
