import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ConversationScreen from './ConversationScreen.tsx'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const sentence = (index: number, text: string) => ({
  type: 'sentence',
  index,
  text,
  audio: null,
  speech_text: null,
})

function sse(events: object[]): Response {
  const body = events.map((e) => `event: ${(e as { type: string }).type}\ndata: ${JSON.stringify(e)}\n\n`)
  return new Response(body.join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}

function mockReply(sentences: string[]) {
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
          ...sentences.map((text, i) => sentence(i, text)),
          {
            type: 'done',
            turn_id: 'a1',
            text: sentences.join(' '),
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

async function ask(text: string) {
  await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
  await screen.findByText('안녕하세요!')
  await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), text)
  await userEvent.click(screen.getByRole('button', { name: '보내기' }))
}

describe('대화 말풍선의 마크다운', () => {
  it('굵게·링크·목록을 그리고 목록 표시 문장 앞에서 줄을 나눈다', async () => {
    mockReply([
      '**세 가지**예요.',
      '- 하나',
      '- [문서](https://example.com/x)',
      '- 셋',
    ])
    render(<ConversationScreen />)
    await ask('알려 줘')
    const list = await screen.findByRole('list', { name: '대화 내용' })
    await vi.waitFor(() => expect(list.querySelectorAll('li li')).toHaveLength(3))
    expect(list.querySelector('strong')?.textContent).toBe('세 가지')
    const link = screen.getByRole('link', { name: '문서' })
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    expect(link).toHaveAttribute('target', '_blank')
  })

  it('답변 속 원시 HTML과 javascript 링크는 글자로만 보인다', async () => {
    mockReply(['<img src=x onerror=alert(1)> 그리고 [눌러](javascript:alert(1))'])
    render(<ConversationScreen />)
    await ask('해 봐')
    const list = await screen.findByRole('list', { name: '대화 내용' })
    await vi.waitFor(() => expect(list.textContent).toContain('<img src=x onerror=alert(1)>'))
    expect(list.querySelector('img')).toBeNull()
    expect(screen.queryByRole('link')).toBeNull()
    expect(list.textContent).toContain('[눌러](javascript:alert(1))')
  })

  it('내 말풍선은 서식 없이 글자 그대로 보인다', async () => {
    mockReply(['네.'])
    render(<ConversationScreen />)
    await ask('**그대로** 보여 줘')
    expect(await screen.findByText('**그대로** 보여 줘')).toBeInTheDocument()
  })
})
