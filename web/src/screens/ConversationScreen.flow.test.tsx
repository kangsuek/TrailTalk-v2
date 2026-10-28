import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { JournalDetail, Turn } from '../core/journal.ts'
import ConversationScreen from './ConversationScreen.tsx'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

const STARTED = {
  session: { id: 's1', mode: 'text', status: 'active', started_at: 'x', ended_at: null },
  greeting: { turn_id: 'g1', text: '안녕하세요! 오늘 어떤 이야기를 할까요?', audio: null },
  persona: { id: 'jenny', name: '제니', ack: [] },
}

const idea = (id: string, sessionId: string, content: string, counts = { idea: 1, todo: 0, memo: 0 }) => ({
  id,
  content,
  starred: false,
  session_id: sessionId,
  created_at: new Date(2026, 9, 21, 9, 0).toISOString(),
  counts,
})

type Handler = (init: RequestInit) => Response | Promise<Response>

function mockServer(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}, ..._rest: unknown[]) => {
    const handler = handlers[`${init.method ?? 'GET'} ${url}`]
    if (!handler) throw new Error(`처리되지 않은 요청: ${init.method ?? 'GET'} ${url}`)
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const startOk: Record<string, Handler> = {
  'POST /api/sessions': () => Response.json(STARTED, { status: 201 }),
}

const closed = (overrides: object = {}) => ({
  session: { ...STARTED.session, status: 'ended' },
  closing: '오늘 아이디어 1개 저장했어요!',
  closing_audio: null,
  saved: { idea: 1, todo: 0, memo: 2 },
  journal_status: 'done',
  ...overrides,
})

function sse(events: object[]): Response {
  const body = events.map((e) => `event: ${(e as { type: string }).type}\ndata: ${JSON.stringify(e)}\n\n`)
  return new Response(body.join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}

async function startConversation() {
  await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
  await screen.findByText(STARTED.greeting.text)
}

describe('시작 화면의 지난 아이디어 카드', () => {
  it('아이디어 카드를 보이고 누르면 그 일지를 연다', async () => {
    mockServer({
      'GET /api/notes/open-ideas?limit=5': () =>
        Response.json([
          idea('n1', 'sA', '산책 코스에 맞춰 **날씨** 알림을 붙이면 어떨까', { idea: 2, todo: 1, memo: 0 }),
          idea('n2', 'sB', '걸음 수 대신 생각 수를 세 보기', { idea: 3, todo: 0, memo: 1 }),
        ]),
    })
    const onOpenJournal = vi.fn()
    render(<ConversationScreen onOpenJournal={onOpenJournal} />)
    const section = await screen.findByRole('region', { name: '지난 아이디어 이어 가기' })
    const first = within(section).getAllByRole('button')[0]
    expect(within(first).getByText('10월 21일')).toBeInTheDocument()
    expect(within(first).getByText('산책 코스에 맞춰 날씨 알림을 붙이면 어떨까')).toBeInTheDocument()
    expect(within(first).getByText('아이디어 2')).toBeInTheDocument()
    expect(within(first).getByText('할 일 1')).toBeInTheDocument()
    expect(within(first).queryByText(/메모/)).toBeNull()
    await userEvent.click(first)
    expect(onOpenJournal).toHaveBeenCalledWith('sA')
  })

  it('없거나 못 불러오면 숨긴다', async () => {
    mockServer({ 'GET /api/notes/open-ideas?limit=5': () => Response.json([]) })
    render(<ConversationScreen />)
    expect(await screen.findByRole('button', { name: '글로 대화 시작' })).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByRole('region', { name: '지난 아이디어 이어 가기' })).toBeNull())
    cleanup()
    mockServer({
      'GET /api/notes/open-ideas?limit=5': () =>
        Response.json({ error: { code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' } }, { status: 500 }),
    })
    render(<ConversationScreen />)
    expect(await screen.findByRole('button', { name: '글로 대화 시작' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '지난 아이디어 이어 가기' })).toBeNull()
  })

  it('새 대화를 끝내고 시작 화면으로 돌아오면 다시 불러온다', async () => {
    let calls = 0
    mockServer({
      ...startOk,
      'GET /api/notes/open-ideas?limit=5': () => {
        calls += 1
        return Response.json([])
      },
    })
    render(<ConversationScreen />)
    await waitFor(() => expect(calls).toBe(1))
    await startConversation()
    // 대화 중에는 부르지 않는다
    expect(calls).toBe(1)
  })
})

describe('종료 확인과 정리', () => {
  it('종료 확인 창에서 계속 대화하면 끝내지 않는다', async () => {
    const fetchMock = mockServer({ ...startOk })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    const dialog = screen.getByRole('alertdialog', { name: '대화 종료 확인' })
    expect(within(dialog).getByText('대화를 끝낼까요?')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: '계속 대화하기' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(screen.getByRole('textbox', { name: '메시지' })).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/end'))).toBe(false)
  })

  it('끝내고 정리하기를 누르면 정리 중 안내와 그만 기다리기를 보이다가 저장 개수를 보인다', async () => {
    let release!: () => void
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/end': () =>
        new Promise<Response>((resolve) => {
          release = () => resolve(Response.json(closed()))
        }),
    })
    const onOpenJournal = vi.fn()
    render(<ConversationScreen onOpenJournal={onOpenJournal} />)
    await startConversation()
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    await userEvent.click(screen.getByRole('button', { name: '끝내고 정리하기' }))
    expect(await screen.findByRole('status', { name: '정리 중' })).toHaveTextContent('최대 45초')
    expect(screen.getByRole('button', { name: '그만 기다리기' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '메시지' })).toBeNull()
    release()
    expect(await screen.findByText('오늘 아이디어 1개 저장했어요!')).toBeInTheDocument()
    const summary = screen.getByRole('region', { name: '오늘의 정리' })
    expect(within(summary).getByText('오늘 저장한 것')).toBeInTheDocument()
    expect(within(summary).getByText('아이디어 1')).toBeInTheDocument()
    expect(within(summary).getByText('할 일 0')).toBeInTheDocument()
    expect(within(summary).getByText('메모 2')).toBeInTheDocument()
    expect(within(summary).queryByText('일지를 정리하고 있어요')).toBeNull() // 정리가 끝났다
    await userEvent.click(within(summary).getByRole('button', { name: '일지에서 보기' }))
    expect(onOpenJournal).toHaveBeenCalledWith('s1')
    expect(screen.getByRole('button', { name: '새 대화 시작' })).toBeInTheDocument()
  })

  it('정리가 아직이면(pending) 일지에서 볼 수 있다고 안내한다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/end': () => Response.json(closed({ journal_status: 'pending' })),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    await userEvent.click(screen.getByRole('button', { name: '끝내고 정리하기' }))
    const summary = await screen.findByRole('region', { name: '오늘의 정리' })
    expect(within(summary).getByText('일지를 정리하고 있어요')).toBeInTheDocument()
  })

  it('그만 기다리기를 누르면 끝난 화면으로 가고 일지에서 볼 수 있다고 안내한다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/end': (init) =>
        new Promise<Response>((_resolve, reject) => {
          init.signal?.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
        }),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    await userEvent.click(screen.getByRole('button', { name: '끝내고 정리하기' }))
    await userEvent.click(await screen.findByRole('button', { name: '그만 기다리기' }))
    expect(await screen.findByText('대화 끝남')).toBeInTheDocument()
    const summary = screen.getByRole('region', { name: '오늘의 정리' })
    expect(within(summary).getByText('일지를 정리하고 있어요')).toBeInTheDocument()
    expect(within(summary).queryByText('오늘 저장한 것')).toBeNull() // 개수는 아직 모른다
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByRole('button', { name: '새 대화 시작' })).toBeInTheDocument()
  })

  it('끝내기 요청이 실패하면 오류를 보이고 대화를 이어 갈 수 있다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/end': () =>
        Response.json({ error: { code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' } }, { status: 500 }),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    await userEvent.click(screen.getByRole('button', { name: '끝내고 정리하기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('서버 내부 오류')
    expect(screen.getByRole('textbox', { name: '메시지' })).toBeEnabled()
  })

  it('끝내기 도구로 끝난 대화는 끝내기 API로 마무리 멘트와 저장 개수를 받는다', async () => {
    const fetchMock = mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () =>
        sse([
          { type: 'turn', turn_id: 'a1' },
          { type: 'sentence', index: 0, text: '오늘도 수고했어요!', audio: null, speech_text: null },
          {
            type: 'done',
            turn_id: 'a1',
            text: '오늘도 수고했어요!',
            interrupted: false,
            session_status: 'ended',
            superseded: false,
          },
        ]),
      'POST /api/sessions/s1/end': () => Response.json(closed({ closing: '오늘 메모 2개 저장했어요!' })),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '오늘은 여기까지{Enter}')
    expect(await screen.findByText('오늘 메모 2개 저장했어요!')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '오늘의 정리' })).getByText('메모 2')).toBeInTheDocument()
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/end'))).toHaveLength(1)
  })
})

function turn(id: string, seq: number, role: Turn['role'], text: string): Turn {
  return { id, seq, role, text, interrupted: false, merged_from: null, created_at: 'x', attachments: [] }
}

function detail(status: 'active' | 'paused' | 'ended'): JournalDetail {
  return {
    session: {
      id: 's9',
      date: '2026-10-22',
      started_at: 'x',
      ended_at: status === 'ended' ? 'y' : null,
      status,
      title: null,
      summary: [],
      tags: [],
      journal_status: null,
      counts: { idea: 0, todo: 0, memo: 0 },
    },
    summary_cites: [],
    citations: [],
    checks: null,
    persona_name: '제니',
    notes: [],
    turns: [turn('t0', 0, 'assistant', '안녕하세요'), turn('t1', 1, 'user', '아까 하던 얘기'), turn('t2', 2, 'assistant', '네 이어서요')],
  }
}

describe('새로고침 뒤 복원', () => {
  it('기억한 진행 중 대화를 전문으로 채우고 같은 세션에 턴을 이어 보낸다(reopen은 부르지 않는다)', async () => {
    const fetchMock = mockServer({
      'GET /api/journal/s9': () => Response.json(detail('active')),
      'POST /api/sessions/s9/turns': () =>
        sse([
          { type: 'turn', turn_id: 'a9' },
          { type: 'sentence', index: 0, text: '이어서 답해요.', audio: null, speech_text: null },
          { type: 'done', turn_id: 'a9', text: '이어서 답해요.', interrupted: false, session_status: 'active', superseded: false },
        ]),
    })
    const onSessionChange = vi.fn()
    render(<ConversationScreen restoreId="s9" onSessionChange={onSessionChange} />)
    expect(screen.getByText('하던 대화를 불러오고 있어요…')).toBeInTheDocument()
    expect(await screen.findByText('아까 하던 얘기')).toBeInTheDocument()
    expect(screen.getByText('네 이어서요')).toBeInTheDocument()
    expect(screen.getByText('제니')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '글로 대화 시작' })).toBeNull()
    expect(onSessionChange).toHaveBeenCalledWith('s9')
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '계속해요{Enter}')
    expect(await screen.findByText('이어서 답해요.')).toBeInTheDocument()
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/reopen'))).toBe(false)
  })

  it('쉬는 중인 대화도 복원한다', async () => {
    mockServer({ 'GET /api/journal/s9': () => Response.json(detail('paused')) })
    render(<ConversationScreen restoreId="s9" />)
    expect(await screen.findByText('아까 하던 얘기')).toBeInTheDocument()
    expect(screen.getByText('쉬는 중')).toBeInTheDocument()
  })

  it('이미 끝났거나 없는 대화는 기억을 지우고 시작 화면을 보인다', async () => {
    mockServer({ 'GET /api/journal/s9': () => Response.json(detail('ended')) })
    const onSessionChange = vi.fn()
    render(<ConversationScreen restoreId="s9" onSessionChange={onSessionChange} />)
    expect(await screen.findByRole('button', { name: '글로 대화 시작' })).toBeInTheDocument()
    expect(onSessionChange).toHaveBeenCalledWith(null)
    cleanup()
    mockServer({
      'GET /api/journal/s9': () =>
        Response.json({ error: { code: 'session_not_found', message: '없어요' } }, { status: 404 }),
    })
    const second = vi.fn()
    render(<ConversationScreen restoreId="s9" onSessionChange={second} />)
    expect(await screen.findByRole('button', { name: '글로 대화 시작' })).toBeInTheDocument()
    expect(second).toHaveBeenCalledWith(null)
  })

  it('서버에 닿지 못하면 시작 화면을 보이되 기억은 지우지 않는다', async () => {
    mockServer({}) // 모든 요청이 연결 오류
    const onSessionChange = vi.fn()
    render(<ConversationScreen restoreId="s9" onSessionChange={onSessionChange} />)
    expect(await screen.findByRole('button', { name: '글로 대화 시작' })).toBeInTheDocument()
    expect(onSessionChange).not.toHaveBeenCalled()
  })
})
