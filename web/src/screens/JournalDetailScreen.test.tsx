import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { JournalDetail, JournalItem, Note, Turn } from '../core/journal.ts'
import JournalDetailScreen from './JournalDetailScreen.tsx'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function session(overrides: Partial<JournalItem> = {}): JournalItem {
  return {
    id: 's1',
    date: '2026-10-22',
    started_at: new Date(2026, 9, 22, 7, 12).toISOString(),
    ended_at: new Date(2026, 9, 22, 7, 50).toISOString(),
    status: 'ended',
    title: '비 오기 전 알림 앱 아이디어',
    summary: ['**걷는 사람**에게는 알림이 쓸모 있다.', '예보는 1시간 단위로 갱신된다.'],
    tags: ['산책', '알림'],
    journal_status: 'done',
    counts: { idea: 2, todo: 1, memo: 0 },
    ...overrides,
  }
}

function note(id: string, kind: Note['kind'], extra: Partial<Note> = {}): Note {
  return { id, kind, content: `${kind} ${id}`, starred: false, done: false, created_at: 'x', cites: [], ...extra }
}

function turn(id: string, seq: number, role: Turn['role'], text: string, extra: Partial<Turn> = {}): Turn {
  return { id, seq, role, text, interrupted: false, merged_from: null, created_at: 'x', attachments: [], ...extra }
}

function detail(overrides: Partial<JournalDetail> = {}): JournalDetail {
  return {
    session: session(),
    summary_cites: [[1], []],
    citations: [{ n: 1, title: '기상청 동네예보', url: 'https://example.com/kma' }],
    checks: ['산 위에서도 예보가 되는지'],
    persona_name: '제니',
    notes: [note('i1', 'idea'), note('i2', 'idea', { starred: true }), note('t1', 'todo')],
    turns: [
      turn('t0', 0, 'assistant', '안녕하세요'),
      turn('t1', 1, 'user', '앞말'),
      turn('t2', 2, 'user', '뒷말', { merged_from: 't1' }),
      turn('t3', 3, 'assistant', '지도를 보니까', { interrupted: true }),
    ],
    ...overrides,
  }
}

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

const get = (d: JournalDetail): Record<string, Handler> => ({
  'GET /api/journal/s1': () => Response.json(d),
})

const bodyOf = (fetchMock: ReturnType<typeof vi.fn>, method: string, url: string) => {
  const call = fetchMock.mock.calls.find(
    ([u, init]) => u === url && (init as RequestInit | undefined)?.method === method,
  )
  return call ? JSON.parse(String((call[1] as RequestInit).body ?? 'null')) : undefined
}

function renderDetail(props: Partial<Parameters<typeof JournalDetailScreen>[0]> = {}) {
  const handlers = {
    onBack: vi.fn(),
    onOpenChat: vi.fn(),
    onResume: vi.fn(),
    onDeleted: vi.fn(),
  }
  render(<JournalDetailScreen id="s1" activeSessionId={null} {...handlers} {...props} />)
  return handlers
}

describe('JournalDetailScreen 내용', () => {
  it('결론·알게 된 것·확인할 것·노트·인용·태그를 순서대로 보인다', async () => {
    mockServer(get(detail()))
    renderDetail()
    expect(await screen.findByRole('heading', { name: '비 오기 전 알림 앱 아이디어' })).toBeInTheDocument()
    expect(screen.getByText('10월 22일 (목) 오전 7:12 · 38분')).toBeInTheDocument()
    const concl = screen.getByRole('region', { name: '결론' })
    expect(within(concl).getByText('걷는 사람').tagName).toBe('STRONG')
    expect(within(concl).getByText('[1]')).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '알게 된 것' })).getByText(/예보는 1시간/)).toBeInTheDocument()
    expect(within(screen.getByRole('region', { name: '확인할 것' })).getByText(/산 위에서도/)).toBeInTheDocument()
    const link = within(screen.getByRole('region', { name: '인용' })).getByRole('link', { name: '기상청 동네예보' })
    expect(link).toHaveAttribute('href', 'https://example.com/kma')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
    const tags = screen.getByRole('list', { name: '태그' })
    expect(within(tags).getByText('#산책')).toBeInTheDocument()
    const order = [...document.querySelectorAll('section[aria-label]')].map((s) => s.getAttribute('aria-label'))
    expect(order.indexOf('결론')).toBeLessThan(order.indexOf('알게 된 것'))
    expect(order.indexOf('알게 된 것')).toBeLessThan(order.indexOf('확인할 것'))
    expect(order.indexOf('확인할 것')).toBeLessThan(order.indexOf('인용'))
  })

  it('노트는 종류별로 묶이고 별표가 위에 온다', async () => {
    mockServer(get(detail()))
    renderDetail()
    const ideas = await screen.findByRole('region', { name: '아이디어' })
    const texts = within(ideas).getAllByRole('listitem').map((li) => li.textContent)
    expect(texts[0]).toContain('idea i2') // 별표
    expect(texts[1]).toContain('idea i1')
    expect(screen.getByRole('region', { name: '할 일' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '메모' })).toBeNull()
  })

  it('예전 형식이면 요약 줄 목록으로 보이고 다시 정리 버튼이 있다', async () => {
    mockServer(get(detail({ checks: null, summary_cites: [], citations: [] })))
    renderDetail()
    expect(await screen.findByRole('region', { name: '요약' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: '결론' })).toBeNull()
    expect(screen.getByRole('button', { name: '다시 정리' })).toBeInTheDocument()
  })

  it('전문은 펼치면 화자 이름과 병합된 뒷말·끊긴 답변이 보인다', async () => {
    mockServer(get(detail()))
    renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: /전문 보기/ }))
    const transcript = screen.getByRole('list', { name: '전문' })
    const items = within(transcript).getAllByRole('listitem')
    expect(items).toHaveLength(3) // 인사말, 병합된 내 말 한 말풍선, 끊긴 답변
    expect(within(items[0]).getByText('제니')).toBeInTheDocument()
    expect(within(items[1]).getByText('나')).toBeInTheDocument()
    expect(within(items[1]).getByText('앞말')).toBeInTheDocument()
    expect(within(items[1]).getByText('뒷말')).toBeInTheDocument()
    expect(within(items[2]).getByText('끝까지 말하지 못했어요')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /접기/ }))
    expect(screen.queryByRole('list', { name: '전문' })).toBeNull()
  })

  it('없는 일지는 안내를 보인다', async () => {
    mockServer({
      'GET /api/journal/s1': () =>
        Response.json({ error: { code: 'session_not_found', message: '없어요' } }, { status: 404 }),
    })
    const { onBack } = renderDetail()
    expect(await screen.findByRole('alert')).toHaveTextContent('이 일지를 찾을 수 없어요')
    await userEvent.click(screen.getByRole('button', { name: '목록으로' }))
    expect(onBack).toHaveBeenCalled()
  })
})

describe('JournalDetailScreen 정리 상태', () => {
  it('정리 중이면 안내와 자리 표시를 보이고 3초마다 갱신해 끝난 것을 채운다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let calls = 0
    mockServer({
      'GET /api/journal/s1': () => {
        calls += 1
        return Response.json(
          calls < 3
            ? detail({
                session: session({ journal_status: 'pending', summary: [], title: null }),
                notes: [],
                checks: null,
                summary_cites: [],
                citations: [],
              })
            : detail(),
        )
      },
    })
    renderDetail()
    expect(await screen.findByRole('status', { name: '정리 중' })).toHaveTextContent('일지를 정리하고 있어요')
    expect(screen.getByRole('heading', { name: '제목 없는 대화' })).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(3000)
    await vi.advanceTimersByTimeAsync(3000)
    expect(await screen.findByRole('region', { name: '결론' })).toBeInTheDocument()
    expect(screen.queryByRole('status', { name: '정리 중' })).toBeNull()
  })

  it('정리 실패면 오류 안내와 다시 정리가 있고 누르면 정리 중이 된다', async () => {
    let retried = false
    mockServer({
      'GET /api/journal/s1': () =>
        Response.json(
          detail({
            session: session({ journal_status: retried ? 'pending' : 'failed', summary: [], title: null }),
            notes: [],
            checks: null,
            summary_cites: [],
            citations: [],
          }),
        ),
      'POST /api/journal/s1/retry': () => {
        retried = true
        return Response.json(session({ journal_status: 'pending' }), { status: 202 })
      },
    })
    renderDetail()
    expect(await screen.findByRole('alert', { name: '정리 실패' })).toHaveTextContent('일지를 정리하지 못했어요')
    await userEvent.click(screen.getByRole('button', { name: '다시 정리' }))
    expect(await screen.findByRole('status', { name: '정리 중' })).toBeInTheDocument()
  })
})

describe('JournalDetailScreen 노트·제목·삭제', () => {
  it('별표를 누르면 바로 올라가고 서버에 보낸다. 실패하면 되돌리고 알린다', async () => {
    const fetchMock = mockServer({
      ...get(detail()),
      'PATCH /api/notes/i1': () => Response.json(note('i1', 'idea', { starred: true })),
      'PATCH /api/notes/i2': () =>
        Response.json({ error: { code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' } }, { status: 500 }),
    })
    renderDetail()
    const ideas = await screen.findByRole('region', { name: '아이디어' })
    const rowOf = (text: string) => within(ideas).getByText(text).closest('li')!
    await userEvent.click(within(rowOf('idea i1')).getByRole('button', { name: '별표' }))
    await waitFor(() => expect(bodyOf(fetchMock, 'PATCH', '/api/notes/i1')).toEqual({ starred: true }))
    expect(within(rowOf('idea i1')).getByRole('button', { name: '별표 해제' })).toBeInTheDocument()
    // 실패: i2의 별표를 풀어 보지만 서버가 거절한다
    await userEvent.click(within(rowOf('idea i2')).getByRole('button', { name: '별표 해제' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('서버 내부 오류')
    expect(within(rowOf('idea i2')).getByRole('button', { name: '별표 해제' })).toBeInTheDocument()
  })

  it('할 일을 완료로 표시한다', async () => {
    const fetchMock = mockServer({
      ...get(detail()),
      'PATCH /api/notes/t1': () => Response.json(note('t1', 'todo', { done: true })),
    })
    renderDetail()
    const todos = await screen.findByRole('region', { name: '할 일' })
    await userEvent.click(within(todos).getByRole('button', { name: '완료로 표시' }))
    await waitFor(() => expect(bodyOf(fetchMock, 'PATCH', '/api/notes/t1')).toEqual({ done: true }))
    expect(await within(todos).findByRole('button', { name: '완료 취소' })).toBeInTheDocument()
    expect(within(todos).getByText('완료')).toBeInTheDocument()
  })

  it('노트 내용을 고친다(저장 전에는 보내지 않는다)', async () => {
    const fetchMock = mockServer({
      ...get(detail()),
      'PATCH /api/notes/i1': (init) =>
        Response.json(note('i1', 'idea', { content: JSON.parse(String(init.body)).content })),
    })
    renderDetail()
    const row = (await screen.findByText('idea i1')).closest('li')!
    await userEvent.click(within(row).getByRole('button', { name: '아이디어 수정' }))
    const box = screen.getByRole('textbox', { name: '아이디어 내용' })
    await userEvent.clear(box)
    await userEvent.type(box, '고친 내용')
    expect(bodyOf(fetchMock, 'PATCH', '/api/notes/i1')).toBeUndefined()
    await userEvent.click(screen.getByRole('button', { name: '저장' }))
    expect(await screen.findByText('고친 내용')).toBeInTheDocument()
    expect(bodyOf(fetchMock, 'PATCH', '/api/notes/i1')).toEqual({ content: '고친 내용' })
  })

  it('빈 내용은 저장할 수 없다', async () => {
    mockServer(get(detail()))
    renderDetail()
    const row = (await screen.findByText('idea i1')).closest('li')!
    await userEvent.click(within(row).getByRole('button', { name: '아이디어 수정' }))
    await userEvent.clear(screen.getByRole('textbox', { name: '아이디어 내용' }))
    expect(screen.getByRole('button', { name: '저장' })).toBeDisabled()
  })

  it('제목 수정 시트에서 고쳐 저장한다', async () => {
    const fetchMock = mockServer({
      ...get(detail()),
      'PATCH /api/journal/s1': (init) =>
        Response.json(session({ title: JSON.parse(String(init.body)).title })),
    })
    renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '더 보기' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '제목 수정' }))
    const dialog = screen.getByRole('dialog', { name: '제목 수정' })
    const input = within(dialog).getByLabelText('대화 제목')
    expect(input).toHaveValue('비 오기 전 알림 앱 아이디어')
    await userEvent.clear(input)
    expect(within(dialog).getByRole('button', { name: '저장' })).toBeDisabled()
    await userEvent.type(input, '  새   제목 ')
    await userEvent.click(within(dialog).getByRole('button', { name: '저장' }))
    expect(await screen.findByRole('heading', { name: '새 제목' })).toBeInTheDocument()
    expect(bodyOf(fetchMock, 'PATCH', '/api/journal/s1')).toEqual({ title: '새 제목' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  it('제목 저장이 실패하면 시트 안에 오류를 보인다', async () => {
    mockServer({
      ...get(detail()),
      'PATCH /api/journal/s1': () =>
        Response.json({ error: { code: 'validation_error', message: '요청 형식이 올바르지 않습니다.' } }, { status: 422 }),
    })
    renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '더 보기' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '제목 수정' }))
    await userEvent.click(screen.getByRole('button', { name: '저장' }))
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('요청 형식')
    expect(screen.getByRole('dialog', { name: '제목 수정' })).toBeInTheDocument()
  })

  it('확인한 뒤 지우면 목록으로 돌아간다', async () => {
    const fetchMock = mockServer({
      ...get(detail()),
      'DELETE /api/journal/s1': () => new Response(null, { status: 204 }),
    })
    const { onDeleted } = renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '더 보기' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '대화 지우기' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '취소' }))
    expect(onDeleted).not.toHaveBeenCalled()
    await userEvent.click(screen.getByRole('button', { name: '더 보기' }))
    await userEvent.click(screen.getByRole('menuitem', { name: '대화 지우기' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '지우기' }))
    await waitFor(() => expect(onDeleted).toHaveBeenCalled())
    expect(fetchMock.mock.calls.some(([u, i]) => u === '/api/journal/s1' && (i as RequestInit).method === 'DELETE')).toBe(true)
  })

  it('진행 중인 대화는 지울 수 없다', async () => {
    mockServer(get(detail({ session: session({ status: 'active', ended_at: null, journal_status: null }) })))
    renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '더 보기' }))
    expect(screen.getByRole('menuitem', { name: /대화 지우기/ })).toBeDisabled()
    expect(screen.getByText('진행 중인 대화는 끝낸 뒤 지울 수 있어요.')).toBeInTheDocument()
  })
})

describe('JournalDetailScreen 이어서 하기', () => {
  const reopened = {
    session: { id: 's1', mode: 'text', status: 'active', started_at: 'x', ended_at: null },
    greeting: { turn_id: 'g', text: '다시 왔네요', audio: null },
    persona: { id: 'jenny', name: '제니', ack: [] },
    turns: [],
  }

  it('글로 이어서는 다시 열어 그 결과를 넘긴다', async () => {
    const fetchMock = mockServer({
      ...get(detail()),
      'POST /api/sessions/s1/reopen': () => Response.json(reopened),
    })
    const { onResume } = renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '글로 이어서' }))
    await waitFor(() => expect(onResume).toHaveBeenCalledWith(reopened, { navigate: true }))
    expect(bodyOf(fetchMock, 'POST', '/api/sessions/s1/reopen')).toEqual({ mode: 'text' })
  })

  it('음성으로 이어서는 음성 방식으로 다시 열고 그 결과를 넘긴다', async () => {
    const voiceReopened = { ...reopened, session: { ...reopened.session, mode: 'voice' } }
    const fetchMock = mockServer({
      ...get(detail()),
      'POST /api/sessions/s1/reopen': () => Response.json(voiceReopened),
    })
    const { onResume } = renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '음성으로 이어서' }))
    await waitFor(() => expect(onResume).toHaveBeenCalledWith(voiceReopened, { navigate: true }))
    expect(bodyOf(fetchMock, 'POST', '/api/sessions/s1/reopen')).toEqual({ mode: 'voice' })
  })

  it('다시 여는 동안은 누른 쪽 버튼만 "여는 중…"이고 둘 다 잠긴다', async () => {
    let finish: () => void = () => {}
    mockServer({
      ...get(detail()),
      'POST /api/sessions/s1/reopen': () =>
        new Promise<Response>((resolve) => {
          finish = () => resolve(Response.json(reopened))
        }),
    })
    renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '음성으로 이어서' }))
    expect(await screen.findByRole('button', { name: '여는 중…' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '글로 이어서' })).toBeDisabled()
    finish()
    await waitFor(() => expect(screen.getByRole('button', { name: '음성으로 이어서' })).toBeEnabled())
  })

  it('다시 열기가 실패하면 오류를 보이고 다시 누를 수 있다', async () => {
    mockServer({
      ...get(detail()),
      'POST /api/sessions/s1/reopen': () =>
        Response.json({ error: { code: 'turn_in_progress', message: '이전 답변이 아직 끝나지 않았습니다.' } }, { status: 409 }),
    })
    const { onResume } = renderDetail()
    await userEvent.click(await screen.findByRole('button', { name: '글로 이어서' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('이전 답변이 아직 끝나지 않았습니다.')
    expect(onResume).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: '글로 이어서' })).toBeEnabled()
  })

  it('다른 대화가 진행 중이면 막고 안내한다', async () => {
    mockServer(get(detail()))
    renderDetail({ activeSessionId: 'other' })
    expect(await screen.findByRole('button', { name: '글로 이어서' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '음성으로 이어서' })).toBeDisabled()
    expect(screen.getByText('진행 중인 대화를 끝낸 뒤 이어서 할 수 있어요.')).toBeInTheDocument()
  })

  it('이 화면이 들고 있는 진행 중 대화는 다시 열지 않고 대화 화면으로 돌아간다', async () => {
    const fetchMock = mockServer(
      get(detail({ session: session({ status: 'active', ended_at: null, journal_status: null }) })),
    )
    const { onOpenChat } = renderDetail({ activeSessionId: 's1' })
    await userEvent.click(await screen.findByRole('button', { name: '대화로 돌아가기' }))
    expect(onOpenChat).toHaveBeenCalled()
    expect(screen.queryByRole('button', { name: '대화 끝내기' })).toBeNull()
    expect(fetchMock.mock.calls.every(([, i]) => (i as RequestInit)?.method !== 'POST')).toBe(true)
  })

  it('열려 있지 않은 진행 중 대화는 이어서와 대화 끝내기를 보인다', async () => {
    let ended = false
    mockServer({
      'GET /api/journal/s1': () =>
        Response.json(
          detail({
            session: session(
              ended
                ? { journal_status: 'done' }
                : { status: 'active', ended_at: null, journal_status: null },
            ),
          }),
        ),
      'POST /api/sessions/s1/end': () => {
        ended = true
        return Response.json({ closing: '끝', saved: { idea: 0, todo: 0, memo: 0 }, journal_status: 'done' })
      },
    })
    renderDetail()
    expect(await screen.findByRole('button', { name: '글로 이어서' })).toBeEnabled()
    await userEvent.click(screen.getByRole('button', { name: '대화 끝내기' }))
    await waitFor(() => expect(screen.queryByRole('button', { name: '대화 끝내기' })).toBeNull())
    expect(screen.getByRole('button', { name: '대화 지우기' })).toBeEnabled()
  })
})
