import { afterEach, describe, expect, it, vi } from 'vitest'
import type { StreamEvent } from '../core/conversation.ts'
import { ApiError, endSession, sendTurn, startSession } from './conversation.ts'

afterEach(() => vi.unstubAllGlobals())

/** 바이트 조각들로 된 SSE 응답. 한글 UTF-8 바이트가 조각 경계에서 잘리게 할 수 있다. */
function sseResponse(chunks: Uint8Array[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk)
      controller.close()
    },
  })
  return new Response(stream, { headers: { 'Content-Type': 'text/event-stream' } })
}

function sse(events: StreamEvent[]): string {
  return events.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join('')
}

const EVENTS: StreamEvent[] = [
  { type: 'turn', turn_id: 'a1' },
  { type: 'sentence', index: 0, text: '바나나는 보통 노란색입니다.', audio: null, speech_text: null },
  {
    type: 'done',
    turn_id: 'a1',
    text: '바나나는 보통 노란색입니다.',
    interrupted: false,
    session_status: 'active',
    superseded: false,
  },
]

describe('sendTurn', () => {
  it('한글 바이트가 조각 경계에서 잘려도 이벤트를 그대로 넘긴다', async () => {
    const bytes = new TextEncoder().encode(sse(EVENTS))
    const chunks: Uint8Array[] = []
    for (let i = 0; i < bytes.length; i += 5) chunks.push(bytes.slice(i, i + 5))
    const fetchMock = vi.fn(async () => sseResponse(chunks))
    vi.stubGlobal('fetch', fetchMock)

    const received: StreamEvent[] = []
    await sendTurn('s 1', '안녕', (e) => received.push(e))
    expect(received).toEqual(EVENTS)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/sessions/s%201/turns')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({ text: '안녕' })
  })

  it('변경성 요청에는 X-TrailTalk 헤더와 JSON 형식을 붙인다(규약 1.5)', async () => {
    const fetchMock = vi.fn(async () => sseResponse([new TextEncoder().encode(sse(EVENTS))]))
    vi.stubGlobal('fetch', fetchMock)
    await sendTurn('s1', '안녕', () => {})
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(init.headers).toEqual({ 'X-TrailTalk': '1', 'Content-Type': 'application/json' })
  })

  it('시작 전 오류는 서버 오류 코드로 던진다', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({
              error: { code: 'turn_in_progress', message: '이전 답변이 아직 끝나지 않았습니다.' },
            }),
            { status: 409 },
          ),
      ),
    )
    const error = await sendTurn('s1', '안녕', () => {}).catch((e) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ code: 'turn_in_progress', status: 409 })
  })

  it('done 없이 스트림이 끝나면 끊김으로 알린다', async () => {
    const partial = new TextEncoder().encode(sse(EVENTS.slice(0, 2)))
    vi.stubGlobal('fetch', vi.fn(async () => sseResponse([partial])))
    const received: StreamEvent[] = []
    const error = await sendTurn('s1', '안녕', (e) => received.push(e)).catch((e) => e)
    expect(received).toHaveLength(2)
    expect(error).toMatchObject({ code: 'stream_closed' })
  })

  it('깨진 이벤트는 bad_event로 던지고 스트림을 취소해 연결을 닫는다', async () => {
    let cancelled = false
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('event: turn\ndata: {not json\n\n'))
      },
      cancel() {
        cancelled = true
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(stream)))
    await expect(sendTurn('s1', '안녕', () => {})).rejects.toMatchObject({ code: 'bad_event' })
    expect(cancelled).toBe(true)
  })

  it('onEvent 예외는 그대로 전달하고 스트림을 취소한다', async () => {
    let cancelled = false
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(sse(EVENTS.slice(0, 1))))
      },
      cancel() {
        cancelled = true
      },
    })
    vi.stubGlobal('fetch', vi.fn(async () => new Response(stream)))
    const boom = new Error('boom')
    await expect(
      sendTurn('s1', '안녕', () => {
        throw boom
      }),
    ).rejects.toBe(boom)
    expect(cancelled).toBe(true)
  })

  it.each(['null', '3', '[]', '{"no_type":1}'])(
    '객체가 아닌 이벤트(%s)는 bad_event로 던진다',
    async (data) => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => sseResponse([new TextEncoder().encode(`data: ${data}\n\n`)])),
      )
      await expect(sendTurn('s1', '안녕', () => {})).rejects.toMatchObject({ code: 'bad_event' })
    },
  )

  it('중단(abort)하면 원래 오류를 그대로 던진다', async () => {
    const controller = new AbortController()
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => {
        controller.abort()
        throw new DOMException('aborted', 'AbortError')
      }),
    )
    await expect(sendTurn('s1', '안녕', () => {}, controller.signal)).rejects.toMatchObject({
      name: 'AbortError',
    })
  })
})

describe('공통 오류 변환', () => {
  it('네트워크 오류와 서버가 꺼져 있을 때의 게이트웨이 오류는 network_error, 그 밖은 http_error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => Promise.reject(new TypeError('fail'))))
    await expect(startSession()).rejects.toMatchObject({ code: 'network_error' })
    for (const status of [502, 503, 504]) {
      vi.stubGlobal('fetch', vi.fn(async () => new Response('bad gateway', { status })))
      await expect(endSession('s1')).rejects.toMatchObject({
        code: 'network_error',
        message: '서버에 연결할 수 없어요.',
      })
    }
    vi.stubGlobal('fetch', vi.fn(async () => new Response('oops', { status: 500 })))
    await expect(endSession('s1')).rejects.toMatchObject({ code: 'http_error', status: 500 })
  })
})

describe('startSession·endSession', () => {
  it('세션 시작은 mode를 보내고 응답을 그대로 돌려준다', async () => {
    const body = { session: { id: 's1' }, greeting: { turn_id: 'g1', text: '안녕', audio: null } }
    const fetchMock = vi.fn(async () => Response.json(body, { status: 201 }))
    vi.stubGlobal('fetch', fetchMock)
    expect(await startSession('text')).toEqual(body)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/sessions')
    expect(JSON.parse(init.body as string)).toEqual({ mode: 'text' })
  })

  it('끝내기는 세션 ID를 경로에 넣어 보낸다', async () => {
    const fetchMock = vi.fn(async () => Response.json({ closing: '끝!' }))
    vi.stubGlobal('fetch', fetchMock)
    await endSession('s 1')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/sessions/s%201/end')
    expect(init.method).toBe('POST')
  })
})

describe('reportLatency', () => {
  it('턴 경로로 지연 필드만 POST한다', async () => {
    const { reportLatency } = await import('./conversation.ts')
    const fetchMock = vi.fn(async () => new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    await reportLatency('s 1', 't/1', 1850, 5400, true)
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('/api/sessions/s%201/turns/t%2F1/latency')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body as string)).toEqual({
      speech_to_request_ms: 1850,
      request_to_playback_ms: 5400,
      first_sound_notice: true,
    })
  })
})
