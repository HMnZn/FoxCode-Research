import type { StreamEvent } from './types'


async function fetchApi(path: string, options: RequestInit = {}) {
  try {
    return await fetch(`/api/${path}`, options)
  } catch (error) {
    if (error instanceof Error && error.name === 'AbortError') throw error
    throw new Error('无法连接本地服务。请运行 npm run dev，或在仓库根目录启动 uv run python -m fox_serve。')
  }
}

export async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetchApi(path, body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(await errorText(response))
  return response.json() as Promise<T>
}

async function errorText(response: Response): Promise<string> {
  if ([502, 503, 504].includes(response.status)) {
    return 'Agent 服务暂不可用。请确认 Python 服务已在 8877 端口启动，然后重新连接。'
  }
  const text = await response.text()
  try { return String(JSON.parse(text).detail ?? text) } catch { return text || response.statusText }
}

export async function consumeEvents(response: Response, onEvent: (event: StreamEvent) => void) {
  if (!response.ok) throw new Error(await errorText(response))
  if (!response.body) throw new Error('流式响应没有 body')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let ended = false
  const consume = () => {
    pending = pending.replace(/\r\n/g, '\n')
    let boundary: number
    while ((boundary = pending.indexOf('\n\n')) >= 0) {
      const frame = pending.slice(0, boundary)
      pending = pending.slice(boundary + 2)
      const data = frame.split('\n').filter(line => line.startsWith('data:'))
        .map(line => line.slice(5).trimStart()).join('\n')
      if (!data) continue
      const event = JSON.parse(data) as StreamEvent
      if (event.type === 'run_end') ended = true
      onEvent(event)
    }
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      pending += decoder.decode(value, { stream: true })
      consume()
    }
    pending += decoder.decode()
    consume()
    if (!ended) throw new Error('连接提前结束，任务状态未知')
  } finally { reader.releaseLock() }
}

export async function run(prompt: string, trialSkill: string, onEvent: (event: StreamEvent) => void, signal: AbortSignal) {
  const response = await fetchApi('run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, trial_skill: trialSkill || null }), signal
  })
  await consumeEvents(response, onEvent)
}
