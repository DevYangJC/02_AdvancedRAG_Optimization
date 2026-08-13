/**
 * SSE 流式问答:fetch + ReadableStream(需 POST body + Bearer 头,不能用 EventSource)
 *
 * 协议:event: meta / delta / done / error
 *   meta  → 回调 onMeta(sources)  引用来源
 *   delta → 回调 onDelta(text)    增量文本
 *   done  → 回调 onDone()         完成
 *   error → 回调 onError(code, msg)
 *
 * 返回 Promise<{ok: boolean, error?: string}>
 */
// 事件回调集合:meta(引用来源)/ delta(增量文本)/ done(完成)/ error(错误)一一对应协议帧;
// signal 由调用方传入时,用于组件卸载或切换会话时中断请求。
export interface SSEHandlers {
  onMeta: (sources: any[]) => void
  onDelta: (text: string) => void
  onDone: () => void
  onError: (code: string, message: string) => void
  signal?: AbortSignal
}

// 为什么用 fetch 而不是 EventSource:EventSource 只支持 GET 且不能自定义请求头,
// 而本接口需要 POST body 与 Bearer token,只能手写 fetch + ReadableStream 解析 SSE 帧。
// 返回值统一收口为 {ok}:调用方据此决定是否进入重试或清理逻辑。
export async function streamChat(
  body: { conversation_id: string | null; content: string },
  handlers: SSEHandlers,
): Promise<{ ok: boolean; error?: string }> {
  // token 直接取自 localStorage:与 axios 拦截器同一来源,保证两条请求链路鉴权一致。
  const token = localStorage.getItem('access_token')
  // AbortController 一物两用:调用方主动取消 + 组件卸载时中止在途请求。
  const controller = new AbortController()
  const signal = handlers.signal ?? controller.signal

  let resp: Response
  try {
    // 只有"请求根本发不出去"的网络错误会走到 catch(如后端未启动);HTTP 状态码错误在下方处理。
    resp = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
      signal,
    })
  } catch (e) {
    return { ok: false, error: '网络连接失败,请检查后端服务是否启动' }
  }

  if (!resp.ok) {
    // 非 2xx:优先取后端错误体里的 message(如 429 限流、token 过期),取不到再用状态码兜底。
    let message = `请求失败(${resp.status})`
    try {
      const data = await resp.json()
      message = data.message || message
    } catch {
      /* ignore */
    }
    return { ok: false, error: message }
  }

  const reader = resp.body?.getReader()
  if (!reader) return { ok: false, error: '响应不支持流式读取' }

  const decoder = new TextDecoder('utf-8')
  // buffer 跨多次 read 累积:SSE 帧可能被切成任意字节段,必须攒到完整帧再解析。
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      // done=true 表示服务端已发送完所有数据,正常退出循环。
      if (done) break
      // 归一化 CRLF → LF(SSE 帧以 \r\n\r\n 分隔,统一后按 \n\n 拆帧)
      buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')

      // 按 SSE 帧边界 "event: xxx\ndata: yyy\n\n" 拆帧
      // 用 while 循环逐帧消费:一次 read 可能包含多帧,必须全部处理完再读下一次。
      let boundary: number
      while ((boundary = buffer.indexOf('\n\n')) !== -1) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)

        // 事件行(event:)与数据行(data:)逐行解析;缺省事件名按 message 处理。
        let eventType = 'message'
        const dataLines: string[] = []
        for (const line of frame.split('\n')) {
          if (line.startsWith('event:')) eventType = line.slice(6).trim()
          else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
        }
        // 没有 data 的帧(如心跳)直接丢弃,不触发任何回调。
        if (!dataLines.length) continue
        let data: any
        try {
          data = JSON.parse(dataLines.join('\n'))
        } catch {
          // 单帧 JSON 损坏:丢弃该帧即可,避免整个流被拖断。
          continue
        }
        // 按事件类型分发:未知事件类型默认忽略,保证协议向后兼容。
        switch (eventType) {
          case 'meta':
            handlers.onMeta(data.sources ?? [])
            break
          case 'delta':
            handlers.onDelta(data.text ?? '')
            break
          case 'done':
            // done 帧是正常结束信号:回调后立即返回成功,不必等流关闭。
            handlers.onDone()
            return { ok: true }
          case 'error':
            handlers.onError(data.code ?? 'ERROR', data.message ?? '回答生成失败')
            return { ok: false, error: data.message }
        }
      }
    }
  } catch (e: any) {
    // AbortError 是调用方主动取消(如切换会话),不算故障,错误文案要与真故障区分。
    if (e?.name === 'AbortError') return { ok: false, error: '已中止' }
    return { ok: false, error: '连接中断' }
  }
  // 流在没有 done 帧的情况下自然结束:视为异常,返回失败让调用方兜底处理。
  return { ok: false, error: '连接意外结束' }
}
