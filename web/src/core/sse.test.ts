import { describe, expect, it } from 'vitest'
import { SseParser, type SseMessage } from './sse.ts'

function parseAll(chunks: string[]): SseMessage[] {
  const parser = new SseParser()
  return [...chunks.flatMap((c) => parser.feed(c)), ...parser.end()]
}

const STREAM =
  'event: turn\ndata: {"type":"turn","turn_id":"t1"}\n\n' +
  'event: sentence\ndata: {"type":"sentence","index":0,"text":"안녕하세요."}\n\n' +
  'event: done\ndata: {"type":"done"}\n\n'

describe('SseParser', () => {
  it('여러 메시지를 순서대로 나눈다', () => {
    const messages = parseAll([STREAM])
    expect(messages.map((m) => m.event)).toEqual(['turn', 'sentence', 'done'])
    expect(JSON.parse(messages[1].data).text).toBe('안녕하세요.')
  })

  it('어느 경계에서 잘려 와도 결과가 같다', () => {
    const whole = parseAll([STREAM])
    for (let size = 1; size <= 7; size++) {
      const chunks: string[] = []
      for (let i = 0; i < STREAM.length; i += size) chunks.push(STREAM.slice(i, i + size))
      expect(parseAll(chunks)).toEqual(whole)
    }
  })

  it('\\r\\n과 \\r 줄 끝을 처리하고, 조각 사이에 걸친 \\r\\n을 한 줄 끝으로 본다', () => {
    expect(parseAll(['event: a\r', '\ndata: 1\r', '\n\r', '\n'])).toEqual([
      { event: 'a', data: '1' },
    ])
    expect(parseAll(['data: x\r\r'])).toEqual([{ event: 'message', data: 'x' }])
  })

  it('여러 data 줄은 줄바꿈으로 잇고, 주석과 모르는 필드는 무시한다', () => {
    expect(parseAll([': ping\nid: 3\ndata: a\ndata:b\nretry: 10\n\n'])).toEqual([
      { event: 'message', data: 'a\nb' },
    ])
  })

  it('U+2028·U+2029는 줄 끝이 아니다', () => {
    const data = '{"text":"줄 바꿈 끝"}'
    expect(parseAll([`data: ${data}\n\n`])).toEqual([{ event: 'message', data }])
  })

  it('빈 줄로 끝나지 않은 마지막 메시지는 버린다', () => {
    expect(parseAll(['data: 1\n\ndata: 2\n'])).toEqual([{ event: 'message', data: '1' }])
  })

  it('스트림 맨 앞의 BOM만 버린다(중간 BOM은 필드 이름의 일부라 그 줄이 무시된다)', () => {
    expect(parseAll(['\uFEFFdata: 1\n\n', '\uFEFFdata: 2\n\n'])).toEqual([
      { event: 'message', data: '1' },
    ])
  })

  it('data 없는 메시지는 내보내지 않는다', () => {
    expect(parseAll(['event: x\n\n'])).toEqual([])
  })
})
