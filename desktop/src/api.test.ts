import { describe, expect, it, vi } from 'vitest'
import { consumeEvents, request } from './api'
import type { StreamEvent } from './types'

function response(chunks: Uint8Array[]) {
  return new Response(new ReadableStream({
    start(controller) {
      chunks.forEach(chunk => controller.enqueue(chunk)); controller.close()
    }
  }))
}

describe('SSE', () => {
  it('handles split UTF-8 characters, frames and CRLF boundaries', async () => {
    const bytes = new TextEncoder().encode('data: {"type":"text_delta","data":{"delta":"你好"}}\r\n\r\ndata: {"type":"run_end","data":{"status":"completed"}}\n\n')
    const chunks = Array.from(bytes, byte => new Uint8Array([byte]))
    const events: StreamEvent[] = []
    await consumeEvents(response(chunks), event => events.push(event))
    expect(events.map(event => event.type)).toEqual(['text_delta', 'run_end'])
    expect(events[0].data.delta).toBe('你好')
  })
  it('reports truncated streams and API errors', async () => {
    await expect(consumeEvents(response([]), () => { })).rejects.toThrow('连接提前结束')
    await expect(consumeEvents(new Response('{"detail":"busy"}', { status: 409 }), () => { })).rejects.toThrow('busy')
  })
  it('explains an unavailable local backend', async () => {
    await expect(consumeEvents(new Response('Bad Gateway', { status: 502 }), () => { })).rejects.toThrow('8877')
    const fetch = vi.spyOn(globalThis, 'fetch').mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(request('state')).rejects.toThrow('npm run dev')
    fetch.mockRestore()
  })
})
