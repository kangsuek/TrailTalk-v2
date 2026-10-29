import { act, cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SessionReopened, SessionStarted } from '../api/conversation.ts'
import type { AudioInputEvent, AudioOutputEvent } from '../core/index.ts'
import ConversationScreen from './ConversationScreen.tsx'
import * as lazyPlatform from './lazyPlatform.ts'
import type { VoiceDeps } from './voiceController.ts'

// 음성 모듈(마이크·재생)은 jsdom에 없어 가짜로 바꾼다. 모듈을 불러왔는지는 시험마다 정한다
vi.mock('./lazyPlatform.ts', () => ({
  preloadPlatform: vi.fn(async () => true),
  lazyAudioInput: vi.fn(),
  lazyAudioOutput: vi.fn(),
}))

beforeEach(() => {
  localStorage.clear()
  vi.stubGlobal('fetch', vi.fn(async () => Response.json([]))) // 시작 화면의 아이디어 목록
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.mocked(lazyPlatform.preloadPlatform).mockImplementation(async () => true)
})

const STARTED: SessionStarted = {
  session: { id: 's1', mode: 'voice', status: 'active', started_at: '2026-10-30T00:00:00Z', ended_at: null },
  greeting: { turn_id: 'g1', text: '안녕하세요! 오늘 어떤 이야기를 할까요?', audio: 'R1JFRVQ=' },
  persona: { id: 'jenny', name: '제니', ack: [] },
}

function setup(overrides: Partial<VoiceDeps> = {}, props: Partial<Parameters<typeof ConversationScreen>[0]> = {}) {
  let outputEvent: (event: AudioOutputEvent) => void = () => {}
  let inputEvent: (event: AudioInputEvent) => void = () => {}
  const out = {
    unlock: vi.fn(async () => {}),
    enqueue: vi.fn(),
    stop: vi.fn(),
    playEffect: vi.fn(),
    dispose: vi.fn(async () => {}),
  }
  const input = { start: vi.fn(async () => {}), stop: vi.fn(async () => {}), setMode: vi.fn(), dispose: vi.fn(async () => {}) }
  const deps: Partial<VoiceDeps> = {
    createInput: (_settings, onEvent) => {
      inputEvent = onEvent
      return input
    },
    createOutput: (onEvent) => {
      outputEvent = onEvent
      return out
    },
    startSession: vi.fn(async () => STARTED),
    sendAudioTurn: vi.fn(async () => {}),
    sendTextTurn: vi.fn(async (_id, _text, onEvent) => {
      onEvent({ type: 'turn', turn_id: 'a1' })
      onEvent({ type: 'sentence', index: 0, text: '글로 받았어요.', audio: null, speech_text: null })
      onEvent({ type: 'done', turn_id: 'a1', text: '글로 받았어요.', interrupted: false, session_status: 'active', superseded: false })
    }),
    reportLatency: vi.fn(async () => {}),
    endSession: vi.fn(async () => ({
      session: STARTED.session,
      closing: '오늘도 즐거웠어요!',
      closing_audio: null,
      saved: { idea: 1, todo: 0, memo: 0 },
      journal_status: 'pending' as const,
    })),
    getProfile: vi.fn(async () => {
      throw new Error('설정값 없음') // 기본 VAD 설정을 쓴다
    }),
    ...overrides,
  }
  const view = render(<ConversationScreen voiceDeps={deps} {...props} />)
  return { deps: deps as VoiceDeps, out, input, view, played: (e: AudioOutputEvent) => act(() => outputEvent(e)), heard: (e: AudioInputEvent) => act(() => inputEvent(e)) }
}

const pressed = (name: string) => screen.getByRole('button', { name }).getAttribute('aria-pressed')

async function startVoiceAndListen(t: ReturnType<typeof setup>) {
  await userEvent.click(screen.getByRole('button', { name: '음성으로' }))
  await userEvent.click(screen.getByRole('button', { name: '음성 대화 시작' }))
  await screen.findByText(STARTED.greeting.text)
  await t.played({ type: 'playback_idle' })
  await waitFor(() => expect(screen.getByText('듣고 있어요')).toBeInTheDocument())
}

describe('시작 화면의 방식 선택', () => {
  it('기억한 방식이 없으면 글이고, 음성을 고르면 마이크 버튼과 안내가 보이며 기기에 기억한다', async () => {
    setup()
    expect(pressed('글로')).toBe('true')
    expect(screen.getByRole('button', { name: '글로 대화 시작' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: '음성으로' })).toBeEnabled())
    await userEvent.click(screen.getByRole('button', { name: '음성으로' }))
    expect(pressed('음성으로')).toBe('true')
    expect(screen.getByRole('button', { name: '음성 대화 시작' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '글로 대화 시작' })).toBeNull()
    expect(screen.getByText('눌러서 시작해요')).toBeInTheDocument()
    expect(localStorage.getItem('trailtalk.mode')).toBe('voice')
  })

  it('다음에 열면 기억한 방식으로 시작한다', () => {
    localStorage.setItem('trailtalk.mode', 'voice')
    setup()
    expect(pressed('음성으로')).toBe('true')
    expect(screen.getByRole('button', { name: '음성 대화 시작' })).toBeInTheDocument()
  })

  it('음성 모듈을 불러오는 동안은 "음성으로"를 막는다', async () => {
    vi.mocked(lazyPlatform.preloadPlatform).mockImplementation(() => new Promise(() => {})) // 계속 불러오는 중
    setup()
    expect(screen.getByRole('button', { name: '음성으로' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '글로 대화 시작' })).toBeEnabled()
  })

  it('음성 모듈을 불러오지 못하면 글로 안내하고 글 대화를 시작할 수 있다', async () => {
    localStorage.setItem('trailtalk.mode', 'voice') // 전에 음성을 골랐어도
    vi.mocked(lazyPlatform.preloadPlatform).mockImplementation(async () => false)
    setup()
    expect(await screen.findByText('음성 기능을 불러오지 못했어요. 글로 대화해 주세요.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '글로 대화 시작' })).toBeEnabled()
    expect(screen.getByRole('button', { name: '음성으로' })).toBeDisabled()
  })
})

describe('음성 대화', () => {
  it('시작하면 인사말을 올리고 재생하는 동안 "말하는 중", 다 들려주면 "듣고 있어요"가 된다', async () => {
    const t = setup()
    await userEvent.click(screen.getByRole('button', { name: '음성으로' }))
    await userEvent.click(screen.getByRole('button', { name: '음성 대화 시작' }))
    await screen.findByText(STARTED.greeting.text)
    expect(t.deps.startSession).toHaveBeenCalledWith('voice', expect.anything())
    expect(screen.getByRole('heading', { name: '제니' })).toBeInTheDocument()
    expect(screen.getByText('말하는 중', { selector: '.chat-status' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /말하는 중/ })).toBeEnabled() // 큰 버튼: 끼어들기
    await t.played({ type: 'playback_idle' })
    expect(await screen.findByText('듣고 있어요')).toBeInTheDocument()
    expect(screen.getByText('편하게 말씀하세요')).toBeInTheDocument()
    expect(screen.getByText('말이 끊기면 자동으로 보내요')).toBeInTheDocument()
  })

  it('대화종료 버튼은 확인 창을 열고, 계속하기는 창만 닫는다', async () => {
    const t = setup()
    await startVoiceAndListen(t)
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    expect(screen.getByRole('alertdialog', { name: '대화 종료 확인' })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '계속 대화하기' }))
    expect(screen.queryByRole('alertdialog')).toBeNull()
    expect(t.deps.endSession).not.toHaveBeenCalled()
    expect(screen.getByText('듣고 있어요')).toBeInTheDocument()
  })

  it('끝내고 정리하기를 누르면 끝내기를 불러 마무리 멘트와 저장 개수를 보인다', async () => {
    const t = setup()
    await startVoiceAndListen(t)
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    await userEvent.click(screen.getByRole('button', { name: '끝내고 정리하기' }))
    await waitFor(() => expect(t.deps.endSession).toHaveBeenCalledTimes(1)) // 한 번만(화면이 다시 부르지 않는다)
    expect(await screen.findByText('오늘도 즐거웠어요!')).toBeInTheDocument()
    expect(screen.getByText('오늘 저장한 것')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '새 대화 시작' })).toBeInTheDocument()
    expect(screen.queryByRole('alertdialog')).toBeNull()
  })

  it('끝내기 도구로 서버가 끝낸 대화도 한 번만 마무리한다', async () => {
    const t = setup({
      sendAudioTurn: vi.fn(async (_id, _audio, onEvent) => {
        onEvent({ type: 'turn', turn_id: 'a1' })
        onEvent({ type: 'sentence', index: 0, text: '안녕히 가세요!', audio: null, speech_text: '안녕히 가세요!' })
        onEvent({ type: 'done', turn_id: 'a1', text: '안녕히 가세요!', interrupted: false, session_status: 'ended', superseded: false })
      }),
    })
    await startVoiceAndListen(t)
    await t.heard({
      type: 'speech_end',
      audio: { bytes: new Uint8Array([1]), mimeType: 'audio/webm', durationMs: 500 },
      speechEndedAt: 1,
    })
    await t.played({ type: 'sentence_played', index: 0 })
    await t.played({ type: 'playback_idle' })
    await waitFor(() => expect(t.deps.endSession).toHaveBeenCalled())
    await screen.findByText('오늘도 즐거웠어요!')
    expect(t.deps.endSession).toHaveBeenCalledTimes(1)
  })

  it('"글"로 바꾸면 입력줄이 보이고 듣는 중에 보낸 글은 글 턴으로 간다', async () => {
    const t = setup()
    await startVoiceAndListen(t)
    expect(pressed('음성으로')).toBe('true')
    await userEvent.click(screen.getByRole('button', { name: '글로' }))
    const box = screen.getByRole('textbox', { name: '메시지' })
    await userEvent.type(box, '글로 말할게요')
    await userEvent.click(screen.getByRole('button', { name: '보내기' }))
    await waitFor(() => expect(t.deps.sendTextTurn).toHaveBeenCalled())
    expect(await screen.findByText('글로 받았어요.')).toBeInTheDocument()
    expect(screen.getByText('글로 말할게요')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '음성으로' })) // 다시 음성 조작 영역
    expect(screen.getByRole('button', { name: /듣는 중|말하는 중/ })).toBeInTheDocument()
  })

  it('듣는 중이 아니면 보내기가 잠긴다', async () => {
    const t = setup()
    await userEvent.click(screen.getByRole('button', { name: '음성으로' }))
    await userEvent.click(screen.getByRole('button', { name: '음성 대화 시작' }))
    await screen.findByText(STARTED.greeting.text) // 인사말 재생 중(말하는 중)
    await userEvent.click(screen.getByRole('button', { name: '글로' }))
    await userEvent.type(screen.getByRole('textbox', { name: '메시지' }), '지금은 안 돼요')
    expect(screen.getByRole('button', { name: '보내기' })).toBeDisabled()
    await t.played({ type: 'playback_idle' })
    await waitFor(() => expect(screen.getByRole('button', { name: '보내기' })).toBeEnabled())
  })

  it('시작에 실패하면 시작 화면에 이유를 보인다', async () => {
    const { ApiError } = await import('../api/conversation.ts')
    setup({
      startSession: vi.fn(async () => {
        throw new ApiError('voice_unavailable', '음성 서비스를 쓸 수 없습니다.', 503)
      }),
    })
    await userEvent.click(screen.getByRole('button', { name: '음성으로' }))
    await userEvent.click(screen.getByRole('button', { name: '음성 대화 시작' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('음성 서비스를 쓸 수 없습니다.')
    expect(screen.getByRole('button', { name: '음성 대화 시작' })).toBeEnabled()
  })
})

describe('일지에서 음성으로 다시 연 대화', () => {
  const REOPENED: SessionReopened = {
    ...STARTED,
    greeting: { turn_id: 'g2', text: '다시 왔네요! 아까 하던 얘기 이어 볼까요?', audio: 'UkVTVU1F' },
    turns: [
      { id: 'g1', seq: 0, role: 'assistant', text: '처음 인사', interrupted: false, merged_from: null, created_at: '2026-10-30T00:00:00Z', attachments: [] },
      { id: 'g2', seq: 1, role: 'assistant', text: '다시 왔네요! 아까 하던 얘기 이어 볼까요?', interrupted: false, merged_from: null, created_at: '2026-10-30T00:01:00Z', attachments: [] },
    ],
  }

  it('시작 요청 없이 전문을 채우고 재개 인사말을 들려준 뒤 듣는다', async () => {
    const onResumed = vi.fn()
    const t = setup({}, { resume: REOPENED, onResumed })
    await screen.findByText('다시 왔네요! 아까 하던 얘기 이어 볼까요?')
    expect(screen.getByText('처음 인사')).toBeInTheDocument() // 이전 말풍선
    expect(t.deps.startSession).not.toHaveBeenCalled()
    expect(onResumed).toHaveBeenCalled()
    expect(t.out.enqueue).toHaveBeenCalledWith({ audio: 'UkVTVU1F', index: null, speechText: null })
    await t.played({ type: 'playback_idle' })
    expect(await screen.findByText('듣고 있어요')).toBeInTheDocument()
  })

  it('글로 다시 연 대화는 글 입력줄로 이어 간다(음성 조작 영역 없음)', async () => {
    setup({}, { resume: { ...REOPENED, session: { ...REOPENED.session, mode: 'text' } } })
    await screen.findByText('다시 왔네요! 아까 하던 얘기 이어 볼까요?')
    expect(screen.getByRole('textbox', { name: '메시지' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: '음성으로' })).toBeNull()
  })
})

describe('내가 말하는 동안', () => {
  it('말을 시작하면 "말하는 중" 말풍선이 보이고, 말이 끝나면 사라진다', async () => {
    const t = setup({ sendAudioTurn: vi.fn(() => new Promise<never>(() => {})) })
    await startVoiceAndListen(t)
    expect(screen.queryByLabelText('말하는 중', { selector: 'li' })).toBeNull()
    await t.heard({ type: 'speech_start' })
    expect(screen.getByLabelText('말하는 중', { selector: 'li' })).toBeInTheDocument()
    await t.heard({
      type: 'speech_end',
      audio: { bytes: new Uint8Array([1]), mimeType: 'audio/webm', durationMs: 500 },
      speechEndedAt: 1,
    })
    await waitFor(() => expect(screen.queryByLabelText('말하는 중', { selector: 'li' })).toBeNull())
  })
})
