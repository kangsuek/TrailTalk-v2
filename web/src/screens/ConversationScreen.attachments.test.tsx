import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DEFAULT_ATTACHMENT_LIMITS } from '../core/attachments.ts'
import ConversationScreen from './ConversationScreen.tsx'

beforeEach(() => {
  // jsdom에는 없는 임시 주소 만들기(방금 고른 이미지의 미리보기)
  URL.createObjectURL = vi.fn(() => 'blob:preview')
  URL.revokeObjectURL = vi.fn()
})

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
  const body = events.map(
    (e) => `event: ${(e as { type: string }).type}\ndata: ${JSON.stringify(e)}\n\n`,
  )
  return new Response(body.join(''), { headers: { 'Content-Type': 'text/event-stream' } })
}

const REPLY = [
  { type: 'turn', turn_id: 'a1' },
  { type: 'sentence', index: 0, text: '잘 봤어요.', audio: null, speech_text: null },
  {
    type: 'done',
    turn_id: 'a1',
    text: '잘 봤어요.',
    interrupted: false,
    session_status: 'active',
    superseded: false,
  },
]

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

const base = (limits = DEFAULT_ATTACHMENT_LIMITS): Record<string, Handler> => ({
  'POST /api/sessions': () => Response.json(STARTED, { status: 201 }),
  'GET /api/profile': () => Response.json({ client: { attachments: limits } }),
})

async function startConversation() {
  await userEvent.click(screen.getByRole('button', { name: '글로 대화 시작' }))
  await screen.findByText(STARTED.greeting.text)
}

const png = () => new File([new Uint8Array([1, 2, 3])], 'map.png', { type: 'image/png' })
const txt = () => new File(['메모'], '코스-메모.txt', { type: 'text/plain' })
const picker = () => screen.getByLabelText('파일 선택', { selector: 'input' }) as HTMLInputElement

describe('ConversationScreen 파일 첨부', () => {
  it('글 대화에는 첨부 버튼과 한도 안내가 있다', async () => {
    mockServer(base())
    render(<ConversationScreen />)
    await startConversation()
    expect(screen.getByRole('button', { name: '파일 첨부' })).toBeInTheDocument()
    expect(screen.getByText('첨부는 글과 함께 보내요 · 최대 3개')).toBeInTheDocument()
  })

  it('고른 파일이 칩으로 보이고 빼기로 뺀다', async () => {
    mockServer(base())
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.upload(picker(), [png(), txt()])
    const chips = await screen.findByRole('list', { name: '보낼 첨부' })
    expect(within(chips).getByText('map.png')).toBeInTheDocument()
    expect(within(chips).getByText('코스-메모.txt')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'map.png 첨부 빼기' }))
    expect(within(chips).queryByText('map.png')).not.toBeInTheDocument()
    expect(within(chips).getByText('코스-메모.txt')).toBeInTheDocument()
  })

  it('서버가 준 한도로 안내한다(개수 초과, 지원하지 않는 형식)', async () => {
    mockServer(base({ ...DEFAULT_ATTACHMENT_LIMITS, max_files: 1 }))
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.upload(picker(), [png(), txt()])
    expect(await screen.findByText('파일은 한 번에 1개까지 보낼 수 있어요.')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '보낼 첨부' }).children).toHaveLength(1)
    expect(screen.getByRole('button', { name: '파일 첨부' })).toBeDisabled()
  })

  it('프로필을 못 받으면 기본 한도로 안내한다', async () => {
    mockServer({ ...base(), 'GET /api/profile': () => Response.json({}, { status: 500 }) })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.upload(picker(), [new File(['x'], 'run.exe')], { applyAccept: false })
    expect(await screen.findByText(/run\.exe: 지원하지 않는 형식/)).toBeInTheDocument()
  })

  it('글이 비면 보내지 못하고 힌트를 보인다', async () => {
    mockServer(base())
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.upload(picker(), [png()])
    expect(await screen.findByText('파일과 함께 보낼 글을 적어 주세요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '보내기' })).toBeDisabled()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '이 지도 봐줘')
    expect(screen.getByRole('button', { name: '보내기' })).toBeEnabled()
    expect(screen.queryByText('파일과 함께 보낼 글을 적어 주세요.')).not.toBeInTheDocument()
  })

  it('글과 파일을 multipart로 보내고 말풍선에 첨부를 보인다', async () => {
    let form: FormData | null = null
    const fetchMock = mockServer({
      ...base(),
      'POST /api/sessions/s1/turns/files': (init) => {
        form = init.body as FormData
        return sse(REPLY)
      },
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.upload(picker(), [png(), txt()])
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '이 지도 봐줘')
    await userEvent.click(screen.getByRole('button', { name: '보내기' }))
    await screen.findByText('잘 봤어요.')

    const sent = form as unknown as FormData
    expect(sent.get('text')).toBe('이 지도 봐줘')
    expect(sent.getAll('files').map((f) => (f as File).name)).toEqual(['map.png', '코스-메모.txt'])
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith('/turns/files'))
    // multipart는 브라우저가 경계가 든 Content-Type을 붙이므로 직접 지정하지 않는다
    const headers = (call?.[1]?.headers ?? {}) as Record<string, string>
    expect(headers['Content-Type']).toBeUndefined()
    const bubble = screen.getByText('이 지도 봐줘').closest('li')!
    expect(within(bubble).getByAltText('map.png')).toHaveAttribute('src', 'blob:preview')
    expect(within(bubble).getByText('코스-메모.txt')).toBeInTheDocument()
    // 보낸 뒤에는 입력창의 첨부가 비워진다
    expect(screen.queryByRole('list', { name: '보낼 첨부' })).not.toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '메시지' })).toHaveValue('')
  })

  it('attachment_* 오류가 오면 쓴 글과 첨부 목록을 입력창에 되돌린다', async () => {
    mockServer({
      ...base(),
      'POST /api/sessions/s1/turns/files': () =>
        Response.json(
          { error: { code: 'attachment_too_large', message: '이미지는 5MB까지 보낼 수 있어요.' } },
          { status: 413 },
        ),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.upload(picker(), [png()])
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '이 지도 봐줘')
    await userEvent.click(screen.getByRole('button', { name: '보내기' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('이미지는 5MB까지 보낼 수 있어요.')
    await waitFor(() =>
      expect(screen.getByRole('textbox', { name: '메시지' })).toHaveValue('이 지도 봐줘'),
    )
    expect(
      within(screen.getByRole('list', { name: '보낼 첨부' })).getByText('map.png'),
    ).toBeInTheDocument()
    // 서버가 받지 못했으니 내 말풍선은 남지 않는다
    expect(screen.queryByRole('listitem', { name: /이 지도 봐줘/ })).not.toBeInTheDocument()
    expect(screen.getByRole('list', { name: '대화 내용' })).not.toHaveTextContent('이 지도 봐줘')
  })

  it('첨부 없이 보내면 기존 글 턴 API를 쓴다', async () => {
    const fetchMock = mockServer({
      ...base(),
      'POST /api/sessions/s1/turns': () => sse(REPLY),
    })
    render(<ConversationScreen />)
    await startConversation()
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '안녕')
    await userEvent.click(screen.getByRole('button', { name: '보내기' }))
    await screen.findByText('잘 봤어요.')
    expect(fetchMock.mock.calls.some(([url]) => url.endsWith('/turns/files'))).toBe(false)
  })
})
