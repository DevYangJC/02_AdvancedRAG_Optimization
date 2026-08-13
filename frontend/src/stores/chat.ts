/**
 * 聊天状态:会话列表、当前会话消息、流式缓冲。
 * 本 store 是聊天工作台的数据中枢:侧栏、消息列表、输入框都只读状态、调动作,
 * 不直接碰 API;流式增量的"原地修改"也在这里完成,组件无需感知数据细节。
 */
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { chatApi } from '@/api/chat'
import type { Conversation, Message, SourceRef } from '@/types/api'

// 流式问答的对外状态:组件据此渲染"空闲/生成中/完成/失败"等界面形态。
export interface StreamState {
  status: 'idle' | 'streaming' | 'done' | 'error'
  errorMsg: string
}

export const useChatStore = defineStore('chat', () => {
  // 四组核心状态:会话列表 / 当前会话 / 当前消息数组 / 流式进度,全部响应式。
  const conversations = ref<Conversation[]>([])
  // current 为 null 表示"尚无会话":ChatView 首次提问时会自动新建一个。
  const current = ref<Conversation | null>(null)
  // messages 在切换会话时整组替换,避免残留上一个会话的消息。
  const messages = ref<Message[]>([])
  // stream 状态由 ChatView 在 SSE 回调里驱动,store 只负责保存与暴露。
  const stream = ref<StreamState>({ status: 'idle', errorMsg: '' })

  // 拉取会话列表:进入聊天页时调用一次;新建/删除后用于局部刷新。
  // 接口是分页的,这里只取第一页(默认 page=1, page_size=50)。
  // 失败无需特殊处理:axios 拦截器已统一弹出错误提示。
  async function loadConversations() {
    const { data } = await chatApi.listConversations()
    conversations.value = data.items
  }

  // 切换会话:先更新当前会话(驱动侧栏高亮与标题),再拉取它的历史消息。
  // 列表里找不到对应 id 时置 null:被删掉的会话不应残留为"当前会话"。
  async function selectConversation(convId: string) {
    const conv = conversations.value.find((c) => c.id === convId)
    current.value = conv ?? null
    const { data } = await chatApi.listMessages(convId)
    messages.value = data.items
  }

  // 新建会话:插入列表头部并设为当前,清空消息区等待首次提问。
  // 返回新会话对象:调用方可直接使用其 id 发起流式问答。
  async function newConversation() {
    const { data } = await chatApi.createConversation()
    conversations.value.unshift(data)
    current.value = data
    messages.value = []
    return data
  }

  // 重命名:成功后把新标题同步到本地列表项,避免整表重拉导致滚动位置跳动。
  async function rename(convId: string, title: string) {
    const { data } = await chatApi.renameConversation(convId, title)
    const item = conversations.value.find((c) => c.id === convId)
    if (item) item.title = data.title
  }

  // 删除会话:本地过滤掉该项;若删的正是当前会话,连消息区一起清空。
  // 删除动作由侧栏二次确认后才触发,这里只负责状态同步。
  async function remove(convId: string) {
    await chatApi.deleteConversation(convId)
    conversations.value = conversations.value.filter((c) => c.id !== convId)
    if (current.value?.id === convId) {
      current.value = null
      messages.value = []
    }
  }

  /** 流式期间维护临时消息(用户提问立即显示,助手回答边流边显示) */
  // 用户消息无需等后端:本地拼一条 completed 消息立刻上屏,同时发起流式请求。
  // id 用 local- 前缀标记"未落库":与后端持久化消息区分,不会与真实 id 冲突。
  // 这条消息不会马上写库,刷新历史或重新加载会话时由后端数据覆盖。
  function pushLocalUser(content: string) {
    messages.value.push({
      id: `local-user-${Date.now()}`,
      conversation_id: current.value?.id ?? '',
      role: 'user',
      content,
      sources: null,
      status: 'completed',
      feedback: null,
      token_count: null,
      created_at: new Date().toISOString(),
    } as Message)
  }

  // 助手消息占位:先以空内容 + streaming 状态上屏,SSE 的 delta 帧逐段填充 content。
  // 返回数组末尾的引用:调用方(ChatView)在 onMeta/onDelta 回调里原地更新同一条消息,
  // 不需要 replace 整个数组——这就是消息"边流边显示"的实现基础。
  function pushLocalAssistant(sources: SourceRef[] | null) {
    messages.value.push({
      id: `local-ai-${Date.now()}`,
      conversation_id: current.value?.id ?? '',
      role: 'assistant',
      content: '',
      sources,
      status: 'streaming',
      feedback: null,
      token_count: null,
      created_at: new Date().toISOString(),
    } as Message)
    return messages.value[messages.value.length - 1]
  }

  // 消息反馈:接口成功后同步更新本地 feedback 字段,驱动按钮的选中高亮。
  // 若消息在本地已被删(异常场景),find 为空则静默跳过。
  async function setFeedback(messageId: string, value: number) {
    await chatApi.setFeedback(messageId, value)
    const msg = messages.value.find((m) => m.id === messageId)
    if (msg) msg.feedback = value
  }

  // 整体复位:登出时由 ChatView 调用,避免下一个账号看到上一个账号的会话。
  // 注意:reset 只清本地内存,不调后端,服务端的会话数据原样保留。
  function reset() {
    conversations.value = []
    current.value = null
    messages.value = []
    stream.value = { status: 'idle', errorMsg: '' }
  }

  return {
    conversations,
    current,
    messages,
    stream,
    loadConversations,
    selectConversation,
    newConversation,
    rename,
    remove,
    pushLocalUser,
    pushLocalAssistant,
    setFeedback,
    reset,
  }
})
