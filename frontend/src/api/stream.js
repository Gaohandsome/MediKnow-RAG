import { TOKEN_KEY } from './http'

/**
 * 调用流式问答接口（SSE over POST）。
 * 通过 fetch + ReadableStream 解析 `data: {...}` 事件。
 */
export async function streamChat(payload, handlers = {}) {
  const { onMeta, onPlan, onCache, onContexts, onSafety, onDelta, onDone, onError, onWarning, signal } = handlers
  const token = localStorage.getItem(TOKEN_KEY) || ''

  let response
  try {
    response = await fetch('/api/v1/chat/stream', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: token ? `Bearer ${token}` : '',
      },
      body: JSON.stringify(payload),
      signal,
    })
  } catch (error) {
    if (error.name !== 'AbortError') {
      onError?.('无法连接服务器，请检查后端服务是否启动')
    }
    return
  }

  if (!response.ok || !response.body) {
    let message = `请求失败（${response.status}）`
    try {
      const data = await response.json()
      message = data?.message || message
    } catch {
      /* 忽略解析异常 */
    }
    onError?.(message)
    return
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatch = (raw) => {
    const dataLines = raw
      .split('\n')
      .filter((line) => line.startsWith('data:'))
      .map((line) => line.slice(5).trim())
    if (!dataLines.length) return
    try {
      const event = JSON.parse(dataLines.join('\n'))
      switch (event.type) {
        case 'meta':
          onMeta?.(event)
          break
        case 'plan':
          onPlan?.(event)
          break
        case 'cache':
          onCache?.(event)
          break
        case 'contexts':
          onContexts?.(event.contexts || [])
          break
        case 'safety':
          onSafety?.(event)
          break
        case 'delta':
          onDelta?.(event.content || '')
          break
        case 'warning':
          onWarning?.(event.message || '')
          break
        case 'done':
          onDone?.(event)
          break
        case 'error':
          onError?.(event.message || '回答生成失败')
          break
        default:
          break
      }
    } catch (error) {
      console.warn('SSE 消息解析失败', error, raw)
    }
  }

  try {
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      let index = buffer.indexOf('\n\n')
      while (index !== -1) {
        const raw = buffer.slice(0, index)
        buffer = buffer.slice(index + 2)
        if (raw.trim()) dispatch(raw)
        index = buffer.indexOf('\n\n')
      }
    }
    if (buffer.trim()) dispatch(buffer)
  } catch (error) {
    if (error.name !== 'AbortError') {
      onError?.('连接中断，请重试')
    }
  }
}
