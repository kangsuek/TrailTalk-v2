import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { JournalItem } from '../core/journal.ts'
import JournalListScreen from './JournalListScreen.tsx'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function item(id: string, overrides: Partial<JournalItem> = {}): JournalItem {
  return {
    id,
    date: '2026-10-22',
    started_at: new Date(2026, 9, 22, 7, 12).toISOString(),
    ended_at: new Date(2026, 9, 22, 7, 50).toISOString(),
    status: 'ended',
    title: `제목 ${id}`,
    summary: [`요약 ${id}`],
    tags: [],
    journal_status: 'done',
    counts: { idea: 0, todo: 0, memo: 0 },
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

const list = (items: JournalItem[]): Record<string, Handler> => ({
  'GET /api/journal': () => Response.json(items),
})

function renderList(props: Partial<Parameters<typeof JournalListScreen>[0]> = {}) {
  const onOpen = vi.fn()
  const onOpenChat = vi.fn()
  render(<JournalListScreen onOpen={onOpen} onOpenChat={onOpenChat} activeSessionId={null} {...props} />)
  return { onOpen, onOpenChat }
}

describe('JournalListScreen', () => {
  it('날짜별로 묶어 제목·요약 첫 줄·노트 개수를 보인다', async () => {
    mockServer(
      list([
        item('a', { counts: { idea: 3, todo: 1, memo: 0 } }),
        item('b', { date: '2026-10-21', summary: ['**굵은** 결론'], counts: { idea: 0, todo: 0, memo: 2 } }),
      ]),
    )
    renderList()
    const first = await screen.findByRole('group', { name: '10월 22일 (목)' })
    expect(within(first).getByText('제목 a')).toBeInTheDocument()
    expect(within(first).getByText('요약 a')).toBeInTheDocument()
    expect(within(first).getByText('아이디어 3')).toBeInTheDocument()
    expect(within(first).getByText('할 일 1')).toBeInTheDocument()
    expect(within(first).queryByText(/메모/)).toBeNull()
    expect(within(first).getByText('오전 7:12 · 38분')).toBeInTheDocument()
    const second = screen.getByRole('group', { name: '10월 21일 (수)' })
    expect(within(second).getByText('굵은 결론')).toBeInTheDocument() // 서식 표시는 뺀다
    expect(within(second).getByText('메모 2')).toBeInTheDocument()
  })

  it('항목을 누르면 상세를 연다', async () => {
    mockServer(list([item('a')]))
    const { onOpen } = renderList()
    await userEvent.click(await screen.findByRole('button', { name: /제목 a/ }))
    expect(onOpen).toHaveBeenCalledWith('a')
  })

  it('이 화면이 들고 있는 진행 중 대화는 대화 화면으로, 다른 진행 중 대화는 상세로 간다', async () => {
    mockServer(
      list([
        item('mine', { status: 'active', ended_at: null, journal_status: null }),
        item('other', { status: 'active', ended_at: null, journal_status: null }),
      ]),
    )
    const { onOpen, onOpenChat } = renderList({ activeSessionId: 'mine' })
    const mine = await screen.findByRole('button', { name: /제목 mine/ })
    expect(within(mine).getByText('대화 중')).toBeInTheDocument()
    expect(within(mine).getByText('대화로 돌아가기')).toBeInTheDocument()
    expect(within(mine).getByText('오전 7:12 · 진행 중')).toBeInTheDocument()
    await userEvent.click(mine)
    expect(onOpenChat).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: /제목 other/ }))
    expect(onOpen).toHaveBeenCalledWith('other')
  })

  it('정리 중·정리 실패 상태를 보이고 제목이 없으면 대신 문구를 쓴다', async () => {
    mockServer(
      list([
        item('p', { journal_status: 'pending', title: null, summary: [] }),
        item('f', { journal_status: 'failed', summary: [] }),
      ]),
    )
    renderList()
    const pending = await screen.findByRole('button', { name: /제목 없는 대화/ })
    expect(within(pending).getByText('일지를 정리하고 있어요')).toBeInTheDocument()
    expect(screen.getByText('정리 실패')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '다시 정리' })).toBeInTheDocument()
  })

  it('다시 정리를 누르면 요청하고 정리 중으로 바뀐다', async () => {
    const retried = item('f', { journal_status: 'pending', summary: [] })
    const fetchMock = mockServer({
      ...list([item('f', { journal_status: 'failed', summary: [] })]),
      'POST /api/journal/f/retry': () => Response.json(retried, { status: 202 }),
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: '다시 정리' }))
    expect(await screen.findByText('일지를 정리하고 있어요')).toBeInTheDocument()
    expect(screen.queryByText('정리 실패')).toBeNull()
    const call = fetchMock.mock.calls.find(([url]) => url === '/api/journal/f/retry')!
    expect((call[1] as RequestInit).method).toBe('POST')
  })

  it('다시 정리 요청이 실패하면 오류를 보이고 항목은 그대로다', async () => {
    mockServer({
      ...list([item('f', { journal_status: 'failed', summary: [] })]),
      'POST /api/journal/f/retry': () =>
        Response.json({ error: { code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' } }, { status: 500 }),
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: '다시 정리' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('서버 내부 오류')
    expect(screen.getByText('정리 실패')).toBeInTheDocument()
  })

  it('정리 중인 동안 3초마다 다시 불러와 끝난 것을 보인다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let calls = 0
    mockServer({
      'GET /api/journal': () => {
        calls += 1
        return Response.json([
          calls < 3
            ? item('p', { journal_status: 'pending', summary: [] })
            : item('p', { journal_status: 'done', summary: ['정리된 요약'] }),
        ])
      },
    })
    renderList()
    expect(await screen.findByText('일지를 정리하고 있어요')).toBeInTheDocument()
    await vi.advanceTimersByTimeAsync(3000)
    await vi.advanceTimersByTimeAsync(3000)
    expect(await screen.findByText('정리된 요약')).toBeInTheDocument()
    const before = calls
    await vi.advanceTimersByTimeAsync(9000)
    expect(calls).toBe(before) // 끝났으니 더 부르지 않는다
  })

  it('정리가 2분 안에 끝나지 않으면 갱신을 멈춘다', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    let calls = 0
    mockServer({
      'GET /api/journal': () => {
        calls += 1
        return Response.json([item('p', { journal_status: 'pending', summary: [] })])
      },
    })
    renderList()
    await screen.findByText('일지를 정리하고 있어요')
    await vi.advanceTimersByTimeAsync(125_000)
    const stopped = calls
    expect(stopped).toBeGreaterThan(30)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(calls).toBe(stopped)
  })

  it('일지가 없으면 안내를 보이고 선택을 막는다', async () => {
    mockServer(list([]))
    renderList()
    expect(await screen.findByText(/아직 일지가 없어요/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '선택' })).toBeDisabled()
  })

  it('목록을 못 불러오면 오류와 다시 불러오기를 보인다', async () => {
    let fail = true
    mockServer({
      'GET /api/journal': () =>
        fail
          ? Response.json({ error: { code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' } }, { status: 500 })
          : Response.json([item('a')]),
    })
    renderList()
    expect(await screen.findByRole('alert')).toHaveTextContent('서버 내부 오류')
    fail = false
    await userEvent.click(screen.getByRole('button', { name: '다시 불러오기' }))
    expect(await screen.findByText('제목 a')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})

describe('JournalListScreen 선택·삭제', () => {
  const three = [
    item('a'),
    item('b', { journal_status: 'pending', summary: [] }),
    item('live', { status: 'active', ended_at: null, journal_status: null }),
  ]

  it('선택 모드에서 진행 중 대화는 고를 수 없고 전체 선택은 지울 수 있는 것만 고른다', async () => {
    mockServer(list(three))
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: '선택' }))
    expect(screen.getByText('항목 선택')).toBeInTheDocument()
    const live = screen.getByRole('checkbox', { name: /제목 live/ })
    expect(live).toBeDisabled()
    expect(screen.getByText('진행 중이라 지울 수 없어요')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '전체 선택' }))
    expect(screen.getByText('2개 선택됨')).toBeInTheDocument()
    expect(screen.getByRole('checkbox', { name: /제목 a/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /제목 b/ })).toBeChecked()
    expect(live).not.toBeChecked()
    await userEvent.click(screen.getByRole('button', { name: '선택 해제' }))
    expect(screen.getByText('항목 선택')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '취소' }))
    expect(screen.getByRole('button', { name: '선택' })).toBeInTheDocument()
  })

  it('확인 창에서 취소하면 지우지 않는다', async () => {
    const fetchMock = mockServer(list(three))
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: '선택' }))
    await userEvent.click(screen.getByRole('checkbox', { name: /제목 a/ }))
    await userEvent.click(screen.getByRole('button', { name: '1개 지우기' }))
    const dialog = screen.getByRole('alertdialog')
    expect(within(dialog).getByText('1개 대화를 지울까요?')).toBeInTheDocument()
    await userEvent.click(within(dialog).getByRole('button', { name: '취소' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(fetchMock.mock.calls.some(([, init]) => (init as RequestInit)?.method === 'DELETE')).toBe(false)
  })

  it('고른 항목을 차례로 지우고 목록에서 뺀다', async () => {
    const order: string[] = []
    let inFlight = 0
    let maxInFlight = 0
    mockServer({
      ...list(three),
      'DELETE /api/journal/a': async () => {
        inFlight += 1
        maxInFlight = Math.max(maxInFlight, inFlight)
        await new Promise((resolve) => setTimeout(resolve, 20))
        inFlight -= 1
        order.push('a')
        return new Response(null, { status: 204 })
      },
      'DELETE /api/journal/b': async () => {
        inFlight += 1
        maxInFlight = Math.max(maxInFlight, inFlight)
        await new Promise((resolve) => setTimeout(resolve, 20))
        inFlight -= 1
        order.push('b')
        return new Response(null, { status: 204 })
      },
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: '선택' }))
    await userEvent.click(screen.getByRole('button', { name: '전체 선택' }))
    await userEvent.click(screen.getByRole('button', { name: '2개 지우기' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '지우기' }))
    await waitFor(() => expect(screen.queryByText('제목 a')).toBeNull())
    expect(screen.queryByText(/제목 b/)).toBeNull()
    expect(screen.getByText('제목 live')).toBeInTheDocument()
    expect(order).toEqual(['a', 'b'])
    expect(maxInFlight).toBe(1) // 동시에 보내지 않는다
    expect(screen.getByRole('button', { name: '선택' })).toBeInTheDocument() // 선택 모드가 끝난다
  })

  it('404는 이미 지운 것으로 보고, 실패한 항목만 선택된 채 남는다', async () => {
    mockServer({
      ...list([item('a'), item('b'), item('c')]),
      'DELETE /api/journal/a': () =>
        Response.json({ error: { code: 'session_not_found', message: '없어요' } }, { status: 404 }),
      'DELETE /api/journal/b': () =>
        Response.json({ error: { code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' } }, { status: 500 }),
      'DELETE /api/journal/c': () => new Response(null, { status: 204 }),
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: '선택' }))
    await userEvent.click(screen.getByRole('button', { name: '전체 선택' }))
    await userEvent.click(screen.getByRole('button', { name: '3개 지우기' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '지우기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('1개를 지우지 못했어요')
    expect(screen.queryByText('제목 a')).toBeNull()
    expect(screen.queryByText('제목 c')).toBeNull()
    expect(screen.getByRole('checkbox', { name: /제목 b/ })).toBeChecked()
    expect(screen.getByText('1개 선택됨')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '1개 지우기' })).toBeInTheDocument()
  })

  it('그사이 진행 중이 된 대화를 지우려 하면 끝낸 뒤 지우라고 안내한다', async () => {
    mockServer({
      ...list([item('a')]),
      'DELETE /api/journal/a': () =>
        Response.json({ error: { code: 'session_active', message: '진행 중' } }, { status: 409 }),
    })
    renderList()
    await userEvent.click(await screen.findByRole('button', { name: '선택' }))
    await userEvent.click(screen.getByRole('checkbox', { name: /제목 a/ }))
    await userEvent.click(screen.getByRole('button', { name: '1개 지우기' }))
    await userEvent.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: '지우기' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('진행 중인 대화는 끝낸 뒤 지울 수 있어요')
  })
})
