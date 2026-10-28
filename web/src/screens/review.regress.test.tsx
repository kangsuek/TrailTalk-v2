import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { forgetRememberedSession, readRememberedSession, writeRememberedSession } from '../hooks/rememberedSession.ts'
import type { JournalDetail, JournalItem, Note } from '../core/journal.ts'
import ConversationScreen from './ConversationScreen.tsx'
import JournalDetailScreen from './JournalDetailScreen.tsx'
import JournalListScreen from './JournalListScreen.tsx'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  window.localStorage.clear()
})

type Handler = (init: RequestInit) => Response | Promise<Response>

function mockServer(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const handler = handlers[`${init.method ?? 'GET'} ${url}`]
    if (!handler) throw new Error(`처리되지 않은 요청: ${init.method ?? 'GET'} ${url}`)
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function sse(events: object[]): Response {
  const body = events.map((e) => `event: ${(e as { type: string }).type}\ndata: ${JSON.stringify(e)}\n\n`)
  return new Response(body.join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}

const STARTED = {
  session: { id: 's1', mode: 'text', status: 'active', started_at: 'x', ended_at: null },
  greeting: { turn_id: 'g1', text: '안녕하세요!', audio: null },
  persona: { id: 'jenny', name: '제니', ack: [] },
}

const closed = (closing: string, saved: object) => ({
  session: { ...STARTED.session, status: 'ended' },
  closing,
  closing_audio: null,
  saved,
  journal_status: 'done',
})

describe('끝낸 대화를 다시 열어 이어 간 뒤 다시 끝낼 때', () => {
  it('끝내기 도구로 끝나도 끝내기 API를 다시 불러 새 마무리와 저장 개수를 보인다', async () => {
    let ends = 0
    mockServer({
      'POST /api/sessions': () => Response.json(STARTED, { status: 201 }),
      'POST /api/sessions/s1/end': () => {
        ends += 1
        return Response.json(
          ends === 1
            ? closed('첫 마무리예요', { idea: 1, todo: 0, memo: 0 })
            : closed('두 번째 마무리예요', { idea: 0, todo: 0, memo: 4 }),
        )
      },
      'POST /api/sessions/s1/turns': () =>
        sse([
          { type: 'turn', turn_id: 'a1' },
          { type: 'sentence', index: 0, text: '여기까지 해요.', audio: null, speech_text: null },
          { type: 'done', turn_id: 'a1', text: '여기까지 해요.', interrupted: false, session_status: 'ended', superseded: false },
        ]),
    })
    const { rerender } = render(<ConversationScreen />)
    await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
    await screen.findByText('안녕하세요!')
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    await userEvent.click(screen.getByRole('button', { name: '끝내고 정리하기' }))
    await screen.findByText('첫 마무리예요')

    // 일지 상세에서 같은 대화를 다시 열었다
    const reopened = {
      session: { ...STARTED.session },
      greeting: { turn_id: 'g2', text: '다시 왔네요', audio: null },
      persona: STARTED.persona,
      turns: [
        { id: 'g2', seq: 0, role: 'assistant', text: '다시 왔네요', interrupted: false, merged_from: null, created_at: 'x', attachments: [] },
      ],
    }
    rerender(<ConversationScreen resume={reopened as never} onResumed={() => {}} />)
    await screen.findByText('다시 왔네요')
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '이제 끝낼게요{Enter}')

    expect(await screen.findByText('두 번째 마무리예요')).toBeInTheDocument()
    const summary = screen.getByRole('region', { name: '오늘의 정리' })
    expect(within(summary).getByText('메모 4')).toBeInTheDocument()
    expect(within(summary).queryByText('아이디어 1')).toBeNull()
    expect(ends).toBe(2)
  })
})

function item(overrides: Partial<JournalItem> = {}): JournalItem {
  return {
    id: 's1',
    date: '2026-10-22',
    started_at: new Date(2026, 9, 22, 7, 12).toISOString(),
    ended_at: null,
    status: 'paused',
    title: '제목',
    summary: [],
    tags: [],
    journal_status: null,
    counts: { idea: 1, todo: 0, memo: 0 },
    ...overrides,
  }
}

const idea = (extra: Partial<Note> = {}): Note => ({
  id: 'i1',
  kind: 'idea',
  content: '아이디어',
  starred: false,
  done: false,
  created_at: 'x',
  cites: [],
  ...extra,
})

function detail(overrides: Partial<JournalDetail> = {}): JournalDetail {
  return {
    session: item(),
    summary_cites: [],
    citations: [],
    checks: [],
    persona_name: '제니',
    notes: [idea()],
    turns: [],
    ...overrides,
  }
}

function renderDetail(props: Partial<Parameters<typeof JournalDetailScreen>[0]> = {}) {
  render(
    <JournalDetailScreen
      id="s1"
      activeSessionId={null}
      onBack={vi.fn()}
      onOpenChat={vi.fn()}
      onResume={vi.fn()}
      onDeleted={vi.fn()}
      {...props}
    />,
  )
}

describe('일지 상세', () => {
  it('이 앱이 열고 있는 쉬는 중 대화는 지울 수 없다', async () => {
    mockServer({ 'GET /api/journal/s1': () => Response.json(detail()) })
    renderDetail({ activeSessionId: 's1' })
    await userEvent.click(await screen.findByRole('button', { name: '더 보기' }))
    expect(screen.getByRole('menuitem', { name: /대화 지우기/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: '대화 지우기' })).toBeDisabled()
  })

  it('앞 요청이 실패해도 뒤 요청의 변경은 되돌리지 않고 실패한 필드만 되돌린다', async () => {
    mockServer({
      'GET /api/journal/s1': () => Response.json(detail({ session: item({ status: 'ended', ended_at: 'x' }) })),
      'PATCH /api/notes/i1': async (init) => {
        const body = JSON.parse(String(init.body))
        if ('starred' in body) {
          await new Promise((resolve) => setTimeout(resolve, 60))
          return Response.json({ error: { code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' } }, { status: 500 })
        }
        return Response.json(idea({ done: true }))
      },
    })
    renderDetail()
    const row = (await screen.findByText('아이디어')).closest('li')!
    await userEvent.click(within(row).getByRole('button', { name: '별표' }))
    await userEvent.click(within(row).getByRole('button', { name: '완료로 표시' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('서버 내부 오류')
    expect(within(row).getByRole('button', { name: '완료 취소' })).toBeInTheDocument() // 완료는 그대로
    expect(within(row).getByRole('button', { name: '별표' })).toBeInTheDocument() // 별표만 되돌아감
  })
})

describe('기억한 세션 ID', () => {
  it('내 세션일 때만 지운다(다른 탭이 기억한 값은 지우지 않는다)', () => {
    writeRememberedSession('s-other')
    forgetRememberedSession('s-mine')
    expect(readRememberedSession()).toBe('s-other')
    forgetRememberedSession('s-other')
    expect(readRememberedSession()).toBeNull()
  })
})

describe('일지 목록 선택', () => {
  it('목록이 갱신돼 사라진 항목은 선택에서 빠진다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let calls = 0
    const a = item({ id: 'a', status: 'ended', journal_status: 'pending', title: '가' })
    const b = item({ id: 'b', status: 'ended', journal_status: 'done', title: '나' })
    mockServer({ 'GET /api/journal': () => Response.json(++calls < 2 ? [a, b] : [b]) })
    render(<JournalListScreen onOpen={vi.fn()} onOpenChat={vi.fn()} activeSessionId={null} />)
    await userEvent.click(await screen.findByRole('button', { name: '선택' }))
    await userEvent.click(screen.getByRole('checkbox', { name: /가/ }))
    expect(screen.getByText('1개 선택됨')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(3000)
    await waitFor(() => expect(screen.queryByText('1개 선택됨')).toBeNull())
    expect(screen.getByText('항목 선택')).toBeInTheDocument()
  })
})
