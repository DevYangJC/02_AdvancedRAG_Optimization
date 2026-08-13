/** useSSE 流式解析单元测试:拆帧(CRLF 归一化)、事件分发、错误处理 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { streamChat } from '@/composables/useSSE'

function makeSseResponse(frames: string[]): Response {
  // 模拟后端 sse-starlette 输出:帧以 CRLF 分隔(关键:验证前端 CRLF 归一化)
  const body = frames.join('\r\n\r\n') + '\r\n\r\n'
  const stream = new ReadableStream({
    start(controller) {
      controller.enqueue(new TextEncoder().encode(body))
      controller.close()
    },
  })
  return new Response(stream, { status: 200 })
}

function makeHandlers() {
  return {
    onMeta: vi.fn(),
    onDelta: vi.fn(),
    onDone: vi.fn(),
    onError: vi.fn(),
  }
}

function setupFetch(mockResp: Response | Promise<Response>) {
  globalThis.fetch = vi.fn().mockResolvedValue(mockResp) as unknown as typeof fetch
}

beforeEach(() => {
  localStorage.setItem('access_token', 'test-token')
})

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('streamChat', () => {
  it('发送 POST 请求并携带 Bearer token', async () => {
    setupFetch(makeSseResponse([`event: done\ndata: {"message_id":"m1","full_text":"ok"}`]))
    await streamChat({ conversation_id: 'c1', content: '你好' }, makeHandlers())

    const [url, init] = (globalThis.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0]
    expect(url).toBe('/api/chat/stream')
    expect(init.method).toBe('POST')
    expect(init.headers.Authorization).toBe('Bearer test-token')
    expect(JSON.parse(init.body).content).toBe('你好')
  })

  it('meta 帧携带引用来源 → onMeta 回调', async () => {
    setupFetch(
      makeSseResponse([
        `event: meta\ndata: {"sources":[{"index":1,"doc_title":"商品说明.md","snippet":"7天无理由"}]}`,
        `event: done\ndata: {"message_id":"m1","full_text":"ok"}`,
      ]),
    )
    const handlers = makeHandlers()
    await streamChat({ conversation_id: 'c1', content: 'q' }, handlers)
    expect(handlers.onMeta).toHaveBeenCalledWith([{ index: 1, doc_title: '商品说明.md', snippet: '7天无理由' }])
  })

  it('delta 帧逐段追加 → onDelta 回调,顺序正确', async () => {
    setupFetch(
      makeSseResponse([
        `event: delta\ndata: {"text":"星云手机"}`,
        `event: delta\ndata: {"text":"电池5000"}`,
        `event: delta\ndata: {"text":"mAh [1]。"}`,
        `event: done\ndata: {"message_id":"m1","full_text":"星云手机电池5000mAh [1]。"}`,
      ]),
    )
    const handlers = makeHandlers()
    const result = await streamChat({ conversation_id: 'c1', content: 'q' }, handlers)
    expect(handlers.onDelta.mock.calls.map((c) => c[0])).toEqual(['星云手机', '电池5000', 'mAh [1]。'])
    expect(handlers.onDone).toHaveBeenCalledTimes(1)
    expect(result).toEqual({ ok: true })
  })

  it('CRLF 帧分隔(后端实际输出格式)可正确拆帧', async () => {
    // 帧与帧之间是 \r\n\r\n,sse-starlette 实际输出;若未归一化会整段无法解析
    setupFetch(makeSseResponse([`event: delta\ndata: {"text":"A"}`]))
    const handlers = makeHandlers()
    await streamChat({ conversation_id: 'c1', content: 'q' }, handlers)
    expect(handlers.onDelta).toHaveBeenCalledWith('A')
  })

  it('跨 chunk 的帧边界正确拼接(流式分块到达)', async () => {
    // 模拟网络把一帧拆成两段到达:第一段只到 "event: de",第二段是剩余部分
    const part1 = `event: delta\ndata: {"text":"你好"}`
    const part2 = `\r\n\r\nevent: done\ndata: {"message_id":"m1","full_text":"你好"}\r\n\r\n`
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(part1))
        controller.enqueue(new TextEncoder().encode(part2))
        controller.close()
      },
    })
    setupFetch(new Response(stream, { status: 200 }))
    const handlers = makeHandlers()
    const result = await streamChat({ conversation_id: 'c1', content: 'q' }, handlers)
    expect(handlers.onDelta).toHaveBeenCalledWith('你好')
    expect(result.ok).toBe(true)
  })

  it('error 事件 → onError 回调并返回失败', async () => {
    setupFetch(
      makeSseResponse([`event: error\ndata: {"code":"STREAM_INTERRUPTED","message":"生成中断"}`]),
    )
    const handlers = makeHandlers()
    const result = await streamChat({ conversation_id: 'c1', content: 'q' }, handlers)
    expect(handlers.onError).toHaveBeenCalledWith('STREAM_INTERRUPTED', '生成中断')
    expect(result.ok).toBe(false)
  })

  it('HTTP 非 200 → 返回后端错误 message', async () => {
    globalThis.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ message: '该会话正在生成回答' }), { status: 409 }),
    ) as unknown as typeof fetch
    const result = await streamChat({ conversation_id: 'c1', content: 'q' }, makeHandlers())
    expect(result).toEqual({ ok: false, error: '该会话正在生成回答' })
  })

  it('网络异常 → 返回网络失败提示', async () => {
    globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('fetch failed')) as unknown as typeof fetch
    const result = await streamChat({ conversation_id: 'c1', content: 'q' }, makeHandlers())
    expect(result.ok).toBe(false)
    expect(result.error).toContain('网络连接失败')
  })
})
