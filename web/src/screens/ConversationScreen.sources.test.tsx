import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ConversationScreen from './ConversationScreen.tsx'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function sse(events: object[]): Response {
  const body = events.map(
    (e) => `event: ${(e as { type: string }).type}\ndata: ${JSON.stringify(e)}\n\n`,
  )
  return new Response(body.join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}

const tool = (phase: string, extra: object = {}) => ({
  type: 'tool',
  phase,
  tool_use_id: 't1',
  name: 'web_search',
  input: null,
  summary: null,
  is_error: false,
  notice: null,
  ...extra,
})

function mockSearchTurn(end: object) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url === '/api/sessions') {
        return Response.json(
          {
            session: { id: 's1', mode: 'text', status: 'active', started_at: 'x', ended_at: null },
            greeting: { turn_id: 'g1', text: '안녕하세요!', audio: null },
            persona: { id: 'jenny', name: '제니', ack: [] },
          },
          { status: 201 },
        )
      }
      if (url === '/api/sessions/s1/turns') {
        return sse([
          { type: 'turn', turn_id: 'a1' },
          tool('start'),
          tool('call', { input: { query: '서울 날씨' } }),
          end,
          { type: 'sentence', index: 0, text: '맑아요.', audio: null, speech_text: null },
          {
            type: 'done',
            turn_id: 'a1',
            text: '맑아요.',
            interrupted: false,
            session_status: 'active',
            superseded: false,
          },
        ])
      }
      throw new Error(`처리되지 않은 요청: ${url}`)
    }),
  )
}

async function ask() {
  await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
  await screen.findByText('안녕하세요!')
  await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '날씨 찾아 줘')
  await userEvent.click(screen.getByRole('button', { name: '보내기' }))
}

describe('답변 말풍선의 출처', () => {
  it('검색 결과의 호스트를 서버가 준 그대로 칩으로 보인다', async () => {
    mockSearchTurn(
      tool('end', {
        summary: {
          kind: 'web_search',
          query: '서울 날씨',
          links: [{ title: '예보', url: 'https://www.kma.go.kr/x' }],
          sources: ['weather.naver.com', 'kma.go.kr'],
        },
      }),
    )
    render(<ConversationScreen />)
    await ask()
    const sources = await screen.findByRole('list', { name: '출처' })
    expect(
      within(sources)
        .getAllByRole('listitem')
        .map((li) => li.textContent),
    ).toEqual(['weather.naver.com', 'kma.go.kr'])
    expect(within(sources).queryByRole('link')).toBeNull() // 링크가 아니라 호스트 글자
    expect(screen.queryByText('검색 완료')).toBeNull()
  })

  it('출처가 없는 검색은 "검색 완료"만, 실패한 읽기는 알림만 보인다', async () => {
    mockSearchTurn(
      tool('end', {
        summary: { kind: 'web_search', query: '서울 날씨', links: [], sources: [] },
      }),
    )
    render(<ConversationScreen />)
    await ask()
    expect(await screen.findByText('검색 완료')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '출처' })).toBeNull()
  })

  it('검색에 실패하면 출처 없이 실패 알림이 보인다', async () => {
    mockSearchTurn(tool('end', { is_error: true }))
    render(<ConversationScreen />)
    await ask()
    expect(await screen.findByText('검색하지 못했어요')).toBeInTheDocument()
    expect(screen.queryByRole('list', { name: '출처' })).toBeNull()
  })
})
