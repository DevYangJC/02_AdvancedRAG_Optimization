/** chat store 单元测试:会话列表/选择/新建/删除/流式期间本地消息 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/api/chat', () => ({
  chatApi: {
    listConversations: vi.fn(),
    createConversation: vi.fn(),
    renameConversation: vi.fn(),
    deleteConversation: vi.fn(),
    listMessages: vi.fn(),
    setFeedback: vi.fn(),
  },
}))

import { chatApi } from '@/api/chat'
import { useChatStore } from '@/stores/chat'

const conv = (id: string, title = '新对话') => ({
  id,
  title,
  created_at: '2026-08-12T10:00:00Z',
  updated_at: '2026-08-12T10:00:00Z',
})
const msg = (id: string, role: 'user' | 'assistant', content: string) => ({
  id,
  conversation_id: 'c1',
  role,
  content,
  sources: role === 'assistant' ? [{ index: 1, doc_title: '商品说明.md' }] : null,
  status: 'completed',
  feedback: null,
  token_count: 10,
  created_at: '2026-08-12T10:00:00Z',
})

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
})

describe('chat store', () => {
  it('loadConversations:填充会话列表', async () => {
    ;(chatApi.listConversations as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { items: [conv('c1'), conv('c2')], total: 2, page: 1, page_size: 50 },
    })
    const store = useChatStore()
    await store.loadConversations()
    expect(store.conversations).toHaveLength(2)
    expect(chatApi.listConversations).toHaveBeenCalled()
  })

  it('selectConversation:加载该会话的历史消息', async () => {
    ;(chatApi.listConversations as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { items: [conv('c1', '我的会话')], total: 1, page: 1, page_size: 50 },
    })
    ;(chatApi.listMessages as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { items: [msg('m1', 'user', '你好'), msg('m2', 'assistant', '你好!')], total: 2, page: 1, page_size: 100 },
    })
    const store = useChatStore()
    await store.loadConversations()
    await store.selectConversation('c1')

    expect(store.current?.title).toBe('我的会话')
    expect(store.messages).toHaveLength(2)
    expect(store.messages[1].sources?.[0].doc_title).toBe('商品说明.md')
  })

  it('newConversation:创建后置为当前会话并清空消息', async () => {
    ;(chatApi.createConversation as ReturnType<typeof vi.fn>).mockResolvedValue({ data: conv('c-new') })
    const store = useChatStore()
    const created = await store.newConversation()
    expect(created.id).toBe('c-new')
    expect(store.current?.id).toBe('c-new')
    expect(store.messages).toHaveLength(0)
  })

  it('rename:修改列表中对应会话标题', async () => {
    ;(chatApi.listConversations as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { items: [conv('c1', '旧标题')], total: 1, page: 1, page_size: 50 },
    })
    ;(chatApi.renameConversation as ReturnType<typeof vi.fn>).mockResolvedValue({ data: conv('c1', '新标题') })
    const store = useChatStore()
    await store.loadConversations()
    await store.rename('c1', '新标题')
    expect(store.conversations[0].title).toBe('新标题')
  })

  it('remove:删除当前会话后回到无会话状态', async () => {
    ;(chatApi.listConversations as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { items: [conv('c1')], total: 1, page: 1, page_size: 50 },
    })
    ;(chatApi.deleteConversation as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { ok: true } })
    const store = useChatStore()
    await store.loadConversations()
    await store.selectConversation('c1')
    await store.remove('c1')

    expect(store.conversations).toHaveLength(0)
    expect(store.current).toBeNull()
    expect(store.messages).toHaveLength(0)
  })

  it('pushLocalUser:流式期间立即显示用户消息', () => {
    const store = useChatStore()
    store.pushLocalUser('问题')
    expect(store.messages).toHaveLength(1)
    expect(store.messages[0].role).toBe('user')
    expect(store.messages[0].content).toBe('问题')
  })

  it('pushLocalAssistant:创建空助手消息并挂上引用来源', () => {
    const store = useChatStore()
    const sources = [{ index: 1, doc_title: '商品说明.md', snippet: '…' }]
    const aiMsg = store.pushLocalAssistant(sources as any)
    expect(aiMsg.role).toBe('assistant')
    expect(aiMsg.content).toBe('')
    expect(aiMsg.status).toBe('streaming')
    expect(aiMsg.sources).toEqual(sources)
    // 返回的是列表中的同一对象(后续流式追加 content 会反映到列表)
    expect(store.messages[store.messages.length - 1]).toBe(aiMsg)
  })

  it('setFeedback:更新本地消息反馈状态', async () => {
    ;(chatApi.listConversations as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { items: [conv('c1')], total: 1, page: 1, page_size: 50 },
    })
    ;(chatApi.listMessages as ReturnType<typeof vi.fn>).mockResolvedValue({
      data: { items: [msg('m1', 'assistant', '回答')], total: 1, page: 1, page_size: 100 },
    })
    ;(chatApi.setFeedback as ReturnType<typeof vi.fn>).mockResolvedValue({ data: { ok: true } })
    const store = useChatStore()
    await store.loadConversations()
    await store.selectConversation('c1')
    await store.setFeedback('m1', 1)
    expect(store.messages[0].feedback).toBe(1)
  })
})
