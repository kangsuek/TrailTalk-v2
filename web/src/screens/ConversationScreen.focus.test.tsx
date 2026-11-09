import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ConversationScreen from './ConversationScreen.tsx'

// 시작·종료 중에 버튼이 잠겨도 키보드·낭독 사용자의 포커스가 사라지지 않는다(접근성, M6).
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const STARTED = {
  session: { id: 's1', mode: 'text', status: 'active', started_at: 'x', ended_at: null },
  greeting: { turn_id: 'g1', text: '안녕하세요! 오늘 어떤 이야기를 할까요?', audio: null },
  persona: { id: 'jenny', name: '제니', ack: [] },
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((r) => {
    resolve = r
  })
  return { promise, resolve }
}

function mockServer(handlers: Record<string, () => Response | Promise<Response>>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const handler = handlers[`${init.method ?? 'GET'} ${url}`]
      if (!handler) return Response.json({}, { status: 200 }) // 사용량 등 이 시험과 무관한 호출
      return handler()
    }),
  )
}

describe('ConversationScreen 포커스 유지', () => {
  it('대화를 시작하는 동안 시작 버튼이 잠겨도 포커스가 화면 구역에 남는다', async () => {
    const start = deferred<Response>()
    mockServer({ 'POST /api/sessions': () => start.promise })
    render(<ConversationScreen />)
    await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
    expect(await screen.findByRole('button', { name: '시작하는 중…' })).toBeDisabled()
    expect(screen.getByRole('region', { name: '대화 시작' })).toHaveFocus()
    start.resolve(Response.json(STARTED, { status: 201 }))
    await screen.findByText(STARTED.greeting.text)
  })

  it('대화를 끝내는 동안 입력창이 정리 화면으로 바뀌어도 포커스가 화면 구역에 남는다', async () => {
    const end = deferred<Response>()
    mockServer({
      'POST /api/sessions': () => Response.json(STARTED, { status: 201 }),
      'POST /api/sessions/s1/end': () => end.promise,
    })
    render(<ConversationScreen />)
    await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
    await screen.findByText(STARTED.greeting.text)
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    await userEvent.click(await screen.findByRole('button', { name: '끝내고 정리하기' }))
    expect(screen.getByRole('region', { name: '대화' })).toHaveFocus()
    expect(document.activeElement).not.toBe(document.body)
    end.resolve(
      Response.json({
        session: { ...STARTED.session, status: 'ended', ended_at: 'y' },
        closing: { turn_id: 'c1', text: '오늘도 즐거웠어요!', audio: null },
        closing_audio: null,
        saved: { idea: 0, todo: 0, memo: 0 },
        journal_status: 'pending',
      }),
    )
  })
})
