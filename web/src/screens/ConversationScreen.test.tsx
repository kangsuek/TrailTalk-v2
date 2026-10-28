import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
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

function sse(events: object[]): Response {
  const body = events.map((e) => `event: ${(e as { type: string }).type}\ndata: ${JSON.stringify(e)}\n\n`)
  return new Response(body.join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}

const turn = (id: string) => ({ type: 'turn', turn_id: id })
const sentence = (index: number, text: string) => ({
  type: 'sentence',
  index,
  text,
  audio: null,
  speech_text: null,
})
const done = (id: string, text: string, status = 'active') => ({
  type: 'done',
  turn_id: id,
  text,
  interrupted: false,
  session_status: status,
  superseded: false,
})

type Handler = (init: RequestInit) => Response | Promise<Response>

function mockServer(handlers: Record<string, Handler>) {
  const fetchMock = vi.fn(async (url: string, init: RequestInit = {}) => {
    const handler = handlers[`${init.method ?? 'GET'} ${url}`]
    if (!handler) throw new Error(`처리되지 않은 요청: ${init.method} ${url}`)
    return handler(init)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

const startOk: Record<string, Handler> = {
  'POST /api/sessions': () => Response.json(STARTED, { status: 201 }),
}

async function startConversation() {
  await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
  await screen.findByText(STARTED.greeting.text)
}

describe('ConversationScreen', () => {
  it('시작 화면에서 버튼을 누르면 캐릭터 이름과 인사말이 보인다', async () => {
    mockServer(startOk)
    render(<ConversationScreen />)
    await startConversation()
    expect(screen.getByText('제니')).toBeInTheDocument()
    expect(screen.getByText('글 대화')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '메시지' })).toBeInTheDocument()
  })

  it('시작에 실패하면 오류를 보이고 다시 시작할 수 있다', async () => {
    mockServer({
      'POST /api/sessions': () =>
        Response.json(
          { error: { code: 'llm_error', message: '대화를 시작하지 못했어요. 잠시 뒤 다시 해 주세요.' } },
          { status: 502 },
        ),
    })
    render(<ConversationScreen />)
    await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('대화를 시작하지 못했어요')
    expect(screen.getByRole('button', { name: '글로 대화 시작' })).toBeEnabled()
  })

  it('Enter로 보내면 내 말풍선과 답변 문장·도구 알림이 쌓인다', async () => {
    const fetchMock = mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () =>
        sse([
          turn('a1'),
          {
            type: 'tool',
            phase: 'start',
            tool_use_id: 't1',
            name: 'save_note',
            input: null,
            summary: null,
            is_error: false,
            notice: null,
          },
          {
            type: 'tool',
            phase: 'call',
            tool_use_id: 't1',
            name: 'save_note',
            input: { kind: 'idea', content: '쓰레기통 지도' },
            summary: null,
            is_error: false,
            notice: null,
          },
          {
            type: 'tool',
            phase: 'end',
            tool_use_id: 't1',
            name: 'save_note',
            input: null,
            summary: { kind: 'result', result: '저장 완료' },
            is_error: false,
            notice: null,
          },
          sentence(0, '저장해 뒀어요.'),
          sentence(1, '누가 쓰면 좋을까요?'),
          done('a1', '저장해 뒀어요. 누가 쓰면 좋을까요?'),
        ]),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '쓰레기통 지도 저장해줘{Enter}')
    expect(await screen.findByText('저장해 뒀어요. 누가 쓰면 좋을까요?')).toBeInTheDocument()
    expect(screen.getByText('쓰레기통 지도 저장해줘')).toBeInTheDocument()
    expect(screen.getByText('아이디어 저장: 쓰레기통 지도')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '메시지' })).toHaveValue('')
    const [, init] = fetchMock.mock.calls.find(([url]) => url === '/api/sessions/s1/turns')!
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ text: '쓰레기통 지도 저장해줘' })
  })

  it('Shift+Enter와 한글 조합 중 Enter는 보내지 않고, 빈 입력은 보낼 수 없다', async () => {
    const fetchMock = mockServer(startOk)
    render(<ConversationScreen />)
    await startConversation()
    const box = screen.getByRole('textbox', { name: '메시지' })
    expect(screen.getByRole('button', { name: '보내기' })).toBeDisabled()
    await userEvent.type(box, '안녕')
    fireEvent.keyDown(box, { key: 'Enter', shiftKey: true })
    fireEvent.keyDown(box, { key: 'Enter', isComposing: true })
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/turns'))).toHaveLength(0)
    expect(screen.getByRole('button', { name: '보내기' })).toBeEnabled()
  })

  it('서버가 받기 전에 실패하면 말풍선을 빼고 글을 입력창으로 되돌린다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () =>
        Response.json(
          { error: { code: 'turn_in_progress', message: '이전 답변이 아직 끝나지 않았습니다.' } },
          { status: 409 },
        ),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '안녕{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('이전 답변이 아직 끝나지 않았습니다.')
    expect(screen.queryByText('안녕', { selector: 'li' })).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '메시지' })).toHaveValue('안녕')
  })

  it('turn 전에 온 error 이벤트도 같은 방식으로 되돌린다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () =>
        sse([{ type: 'error', code: 'turn_in_progress', message: '이전 답변이 아직 끝나지 않았습니다.' }]),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '안녕{Enter}')
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '메시지' })).toHaveValue('안녕')
  })

  it('전송이 실패해도 그 사이 새로 쓰던 글은 덮어쓰지 않는다', async () => {
    let fail: (response: Response) => void = () => {}
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () => new Promise<Response>((resolve) => (fail = resolve)),
    })
    render(<ConversationScreen />)
    await startConversation()
    const box = screen.getByRole('textbox', { name: '메시지' })
    await userEvent.type(box, '첫 글{Enter}')
    await userEvent.type(box, '다음 글')
    fail(
      Response.json(
        { error: { code: 'turn_in_progress', message: '이전 답변이 아직 끝나지 않았습니다.' } },
        { status: 409 },
      ),
    )
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(box).toHaveValue('다음 글')
  })

  it('세션이 이미 끝났다는 오류면 끝난 화면으로 가고 글은 되돌리지 않는다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () =>
        Response.json({ error: { code: 'session_ended', message: '이미 끝난 대화입니다.' } }, { status: 409 }),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '안녕{Enter}')
    expect(await screen.findByRole('button', { name: '새 대화 시작' })).toBeInTheDocument()
    expect(screen.queryByRole('textbox', { name: '메시지' })).not.toBeInTheDocument()
  })

  it('도구가 대화를 끝냈다고(done.session_status=ended) 알리면 끝난 화면이 된다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () =>
        sse([turn('a1'), sentence(0, '오늘도 수고했어요!'), done('a1', '오늘도 수고했어요!', 'ended')]),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '오늘은 여기까지{Enter}')
    expect(await screen.findByText('오늘도 수고했어요!')).toBeInTheDocument()
    expect(screen.getByText('대화 끝남')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '새 대화 시작' })).toBeInTheDocument()
  })

  it('답변 도중 스트림이 끊기면 끊긴 답변으로 표시하고 오류를 보인다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/turns': () => sse([turn('a1'), sentence(0, '첫 문장.')]),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '안녕{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('연결이 끊겼어요')
    expect(screen.getByText('답변이 끊겼어요')).toBeInTheDocument()
    expect(screen.getByText('첫 문장.')).toBeInTheDocument()
  })

  it('대화종료를 누르면 마무리 멘트를 보이고 새 대화를 시작할 수 있다', async () => {
    mockServer({
      ...startOk,
      'POST /api/sessions/s1/end': () =>
        Response.json({
          session: { ...STARTED.session, status: 'ended' },
          closing: '오늘 아이디어 1개 저장했어요!',
          closing_audio: null,
          saved: { idea: 1, todo: 0, memo: 0 },
          journal_status: null,
        }),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    // 종료 확인 창(대화 11)에서 끝내고 정리하기를 고른다
    await userEvent.click(screen.getByRole('button', { name: '끝내고 정리하기' }))
    expect(await screen.findByText('오늘 아이디어 1개 저장했어요!')).toBeInTheDocument()
    expect(screen.getByText('대화 끝남')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '새 대화 시작' }))
    await waitFor(() => expect(screen.getByText(STARTED.greeting.text)).toBeInTheDocument())
    expect(screen.queryByText('오늘 아이디어 1개 저장했어요!')).not.toBeInTheDocument()
  })
})
