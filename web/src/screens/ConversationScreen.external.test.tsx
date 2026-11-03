import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ConversationScreen from './ConversationScreen.tsx'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

// 외부 MCP 도구(M5-13 ⑦): 서버 이름 없이 "<도구> 사용 중/완료"와 결과를 글자 그대로 보인다

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
  name: 'mcp__secretsrv__search_place',
  input: null,
  summary: null,
  is_error: false,
  notice: null,
  ...extra,
})

function mockTurn(end: object) {
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
          tool('call'),
          end,
          { type: 'sentence', index: 0, text: '찾았어요.', audio: null, speech_text: null },
          {
            type: 'done',
            turn_id: 'a1',
            text: '찾았어요.',
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
  await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '근처 찾아 줘')
  await userEvent.click(screen.getByRole('button', { name: '보내기' }))
}

describe('외부 MCP 도구 알림', () => {
  it('서버 이름 없이 도구 이름만 보이고 결과는 마크다운 없이 글자 그대로 보인다', async () => {
    mockTurn(tool('end', { summary: { kind: 'result', result: '**굵게** <b>x</b> `코드`' } }))
    render(<ConversationScreen />)
    await ask()
    expect(await screen.findByText('search_place 사용 완료')).toBeInTheDocument()
    const result = screen.getByText('**굵게** <b>x</b> `코드`')
    expect(result.tagName).toBe('P') // 굵게·코드·태그로 바뀌지 않았다
    expect(result.querySelector('strong, b, code')).toBeNull()
    expect(screen.queryByText(/secretsrv/)).toBeNull() // 서버 이름은 어디에도 보이지 않는다
  })

  it('실패하면 실패 알림만 보이고 결과는 없다', async () => {
    mockTurn(tool('end', { is_error: true }))
    render(<ConversationScreen />)
    await ask()
    expect(await screen.findByText('search_place 사용하지 못했어요')).toBeInTheDocument()
    expect(document.querySelector('.tool-result')).toBeNull()
  })
})
