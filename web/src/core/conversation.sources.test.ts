import { describe, expect, it } from 'vitest'
import { messagesFromTurns, sourceHosts, toolNotice, type ToolState } from './conversation.ts'
import { groupTurns, type Turn } from './journal.ts'

const search = (sources: string[], patch: Partial<ToolState> = {}): ToolState => ({
  id: 't',
  name: 'web_search',
  phase: 'end',
  input: null,
  summary: { kind: 'web_search', query: 'q', links: [], sources },
  isError: false,
  ...patch,
})

const fetched = (
  host: string | null,
  code: number | null,
  patch: Partial<ToolState> = {},
): ToolState => ({
  id: 'f',
  name: 'web_fetch',
  phase: 'end',
  input: null,
  summary: { kind: 'web_fetch', code, bytes: 10, url: host && `https://${host}/`, host },
  isError: false,
  ...patch,
})

describe('sourceHosts', () => {
  it('검색·읽기 요약의 호스트를 중복 없이 모은다', () => {
    const tools = [search(['a.kr', 'b.com']), fetched('b.com', 200), fetched('c.net', 200)]
    expect(sourceHosts({ tools })).toEqual(['a.kr', 'b.com', 'c.net'])
  })

  it('실패한 도구·끝나지 않은 도구·읽지 못한 페이지는 뺀다', () => {
    const tools = [
      search(['a.kr'], { isError: true }),
      search(['b.kr'], { phase: 'call' }),
      fetched('c.kr', 404),
      fetched(null, 200),
      { ...search([]), name: 'save_note', summary: { kind: 'result' as const, result: 'x' } },
    ]
    expect(sourceHosts({ tools })).toEqual([])
  })

  it('저장된 출처가 먼저고 다섯 개까지만 보인다', () => {
    const sources = ['1.kr', '2.kr', '3.kr']
    expect(sourceHosts({ tools: [search(['4.kr', '5.kr', '6.kr'])], sources })).toEqual([
      '1.kr',
      '2.kr',
      '3.kr',
      '4.kr',
      '5.kr',
    ])
  })
})

describe('검색 알림', () => {
  it.each<[ToolState, string | null]>([
    [search([], { phase: 'start' }), '검색 중…'],
    [search([], { phase: 'call', input: { query: '서울 날씨' } }), "'서울 날씨' 검색 중…"],
    [search(['a.kr']), null], // 출처 칩이 대신 보인다
    [search([]), '검색 완료'],
    [search([], { isError: true }), '검색하지 못했어요'],
    [fetched('a.kr', 200, { phase: 'start' }), '페이지 읽는 중…'],
    [fetched('a.kr', 200), null],
    [fetched(null, 200), '페이지 읽기 완료'],
    [fetched('a.kr', 404), '페이지를 읽지 못했어요'],
    [fetched('a.kr', 200, { isError: true }), '페이지를 읽지 못했어요'],
  ])('%#', (tool, expected) => {
    expect(toolNotice(tool)).toBe(expected)
  })
})

const turn = (patch: Partial<Turn>): Turn => ({
  id: 'x',
  seq: 1,
  role: 'assistant',
  text: '답',
  interrupted: false,
  merged_from: null,
  created_at: 'x',
  attachments: [],
  ...patch,
})

describe('저장된 전문의 출처', () => {
  it('다시 연 대화의 답변 말풍선에 출처가 실린다', () => {
    const messages = messagesFromTurns([
      turn({ id: 'a', sources: ['kma.go.kr'] }),
      turn({ id: 'b', seq: 2, sources: [] }),
      turn({ id: 'c', seq: 3 }),
    ])
    expect(messages.map((m) => (m.role === 'assistant' ? m.sources : 'user'))).toEqual([
      ['kma.go.kr'],
      undefined,
      undefined,
    ])
  })

  it('병합된 뒷말의 출처는 앞말 말풍선에 중복 없이 합친다', () => {
    const bubbles = groupTurns([
      turn({ id: 'a', sources: ['a.kr', 'b.kr'] }),
      turn({ id: 'b', seq: 2, merged_from: 'a', sources: ['b.kr', 'c.kr'] }),
    ])
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].sources).toEqual(['a.kr', 'b.kr', 'c.kr'])
  })
})
