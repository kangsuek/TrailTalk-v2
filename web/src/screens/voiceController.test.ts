import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, type SessionReopened, type SessionStarted } from '../api/conversation.ts'
import type { StreamEvent } from '../core/conversation.ts'
import type { AudioInputEvent, AudioOutputEvent, RecordedAudio, SessionState } from '../core/index.ts'
import { createVoiceController, type VoiceDeps } from './voiceController.ts'

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

// 가짜 타이머를 쓴 시험이 실패해도 뒤 시험(flush는 실제 타이머가 필요하다)에 번지지 않게 한다
afterEach(() => vi.useRealTimers())

const AUDIO: RecordedAudio = {
  bytes: new Uint8Array([1, 2, 3]),
  mimeType: 'audio/webm;codecs=opus',
  durationMs: 1200,
}

const STARTED: SessionStarted = {
  session: { id: 's1', mode: 'voice', status: 'active', started_at: '2026-10-30T00:00:00Z', ended_at: null },
  greeting: { turn_id: 'g1', text: '안녕하세요!', audio: 'R1JFRVQ=' },
  persona: { id: 'jenny', name: '제니', ack: [] },
}

const reply = (extra: StreamEvent[] = []): StreamEvent[] => [
  { type: 'transcript', text: '내가 한 말' },
  { type: 'turn', turn_id: 'a1' },
  { type: 'sentence', index: 0, text: '첫 문장.', audio: 'QQ==', speech_text: null },
  { type: 'sentence', index: 1, text: '둘째 문장.', audio: null, speech_text: '둘째 문장.' },
  ...extra,
  {
    type: 'done',
    turn_id: 'a1',
    text: '첫 문장. 둘째 문장.',
    interrupted: false,
    session_status: 'active',
    superseded: false,
  },
]

function setup(overrides: Partial<VoiceDeps> = {}) {
  let inputEvent: (event: AudioInputEvent) => void = () => {}
  let outputEvent: (event: AudioOutputEvent) => void = () => {}
  let clock = 1000
  const input = {
    start: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    setMode: vi.fn(),
    dispose: vi.fn(async () => {}),
  }
  const out = {
    unlock: vi.fn(async () => {}),
    enqueue: vi.fn(),
    stop: vi.fn(),
    playEffect: vi.fn(),
    dispose: vi.fn(async () => {}),
  }
  const actions: unknown[] = []
  const states: SessionState[] = []
  const closed: unknown[] = []
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
    sendAudioTurn: vi.fn(async (_id, _audio, onEvent) => {
      for (const event of reply()) onEvent(event)
    }),
    sendTextTurn: vi.fn(async (_id, _text, onEvent) => {
      for (const event of reply().slice(1)) onEvent(event)
    }),
    reportLatency: vi.fn(async () => {}),
    endSession: vi.fn(
      async () =>
        ({
          session: STARTED.session,
          closing: '오늘도 즐거웠어요!',
          closing_audio: 'Q0xPU0U=',
          saved: { idea: 1, todo: 0, memo: 0 },
          journal_status: 'pending',
        }) as never,
    ),
    getProfile: vi.fn(
      async () =>
        ({
          client: {
            vad: {
              speech_threshold: 0.5,
              silence_threshold: 0.25,
              playback_speech_threshold: 0.8,
              playback_silence_threshold: 0.65,
              end_of_speech_silence_ms: 1800,
              min_speech_ms: 300,
            },
            session: { idle_timeout_minutes: 30 },
          },
        }) as never,
    ),
    now: () => clock,
    ...overrides,
  }
  const controller = createVoiceController({
    dispatch: (action) => actions.push(action),
    onState: (state) => states.push(state),
    onClosed: (id, value) => closed.push([id, value]),
    deps,
  })
  const last = () => states.at(-1)
  return {
    controller,
    deps: deps as VoiceDeps,
    input,
    out,
    actions,
    states,
    closed,
    last,
    advance: (ms: number) => (clock += ms),
    heard: (event: AudioInputEvent) => inputEvent(event),
    played: (event: AudioOutputEvent) => outputEvent(event),
    actionTypes: () => actions.map((a) => (a as { type: string }).type),
  }
}

/** 시작해서 인사말을 다 듣고 듣기 상태가 된다 */
async function listening(t = setup()) {
  t.controller.tap()
  await flush()
  t.played({ type: 'playback_idle' })
  await flush()
  expect(t.last()?.name).toBe('listening')
  return t
}

const speech = (t: ReturnType<typeof setup>) => {
  t.heard({ type: 'speech_end', audio: AUDIO, speechEndedAt: 900 })
}

describe('음성 대화 시작', () => {
  it('큰 버튼으로 시작하면 인사말을 올리고 재생한 뒤 듣기로 간다', async () => {
    const t = setup()
    t.controller.tap()
    expect(t.out.unlock).toHaveBeenCalledTimes(1) // 사용자 동작 안에서 오디오를 연다
    await flush()
    expect(t.deps.startSession).toHaveBeenCalledWith('voice', expect.anything())
    expect(t.actions).toContainEqual({
      type: 'started',
      sessionId: 's1',
      personaName: '제니',
      greeting: { turnId: 'g1', text: '안녕하세요!' },
    })
    expect(t.out.enqueue).toHaveBeenCalledWith({ audio: 'R1JFRVQ=', index: null, speechText: null })
    expect(t.last()?.name).toBe('speaking') // 인사말을 재생하는 동안

    t.played({ type: 'playback_idle' })
    await flush()
    expect(t.last()?.name).toBe('listening')
    expect(t.input.start).toHaveBeenCalled()
    expect(t.out.playEffect).toHaveBeenCalledWith('listen')
  })

  it('인사말 소리가 없으면(합성 실패) 글을 기기 TTS용 speechText로 넘긴다', async () => {
    const t = setup({
      startSession: vi.fn(async () => ({ ...STARTED, greeting: { turn_id: 'g1', text: '안녕!', audio: null } }) as never),
    })
    t.controller.tap()
    await flush()
    expect(t.out.enqueue).toHaveBeenCalledWith({ audio: null, index: null, speechText: '안녕!' })
  })

  it('시작에 실패하면 알리고 대기로 돌아간다', async () => {
    const t = setup({
      startSession: vi.fn(async () => {
        throw new ApiError('voice_unavailable', '음성 서비스를 쓸 수 없습니다.', 503)
      }),
    })
    t.controller.tap()
    await flush()
    expect(t.last()?.name).toBe('idle')
    expect(t.actions).toContainEqual({ type: 'failed', message: '음성 서비스를 쓸 수 없습니다.' })
  })

  it('서버 설정값(VAD)을 받아 마이크를 만든다', async () => {
    const created = vi.fn()
    const quiet = { start: async () => {}, stop: async () => {}, setMode: () => {}, dispose: async () => {} }
    const t = setup({
      createInput: (settings) => {
        created(settings)
        return quiet
      },
    })
    t.controller.tap()
    await flush()
    t.played({ type: 'playback_idle' })
    await flush()
    expect(created).toHaveBeenCalledWith(expect.objectContaining({ endOfSpeechSilenceMs: 1800, minSpeechMs: 300 }))
  })
})

describe('한 턴', () => {
  it('말이 끝나면 올려 인식하고, 답변 문장을 소리와 함께 대기열에 넣고, 다 들려주면 다시 듣는다', async () => {
    const t = await listening()
    speech(t)
    await flush()
    expect(t.deps.sendAudioTurn).toHaveBeenCalledWith('s1', AUDIO, expect.any(Function), expect.anything())
    // transcript → 내 말풍선, turn → 답변 말풍선
    expect(t.actionTypes()).toEqual(expect.arrayContaining(['started', 'event']))
    expect(t.actions).toContainEqual({ type: 'event', event: { type: 'transcript', text: '내가 한 말' } })
    expect(t.out.enqueue).toHaveBeenCalledWith({ audio: 'QQ==', index: 0, speechText: null })
    expect(t.out.enqueue).toHaveBeenCalledWith({ audio: null, index: 1, speechText: '둘째 문장.' })
    expect(t.last()?.name).toBe('speaking')
    expect(t.input.stop).not.toHaveBeenCalled() // 재생 중에도 마이크는 켜 둔다(끼어들기)

    t.played({ type: 'sentence_played', index: 0 })
    t.played({ type: 'sentence_played', index: 1 })
    t.played({ type: 'playback_idle' })
    await flush()
    expect(t.last()?.name).toBe('listening')
  })

  it('첫 답변 소리가 나면 지연을 한 번만 보고한다', async () => {
    const t = await listening()
    t.advance(0)
    speech(t)
    await flush()
    t.advance(5400)
    t.played({ type: 'started', index: 0 })
    t.played({ type: 'started', index: 1 })
    await flush()
    expect(t.deps.reportLatency).toHaveBeenCalledTimes(1)
    expect(t.deps.reportLatency).toHaveBeenCalledWith('s1', 'a1', expect.any(Number), 5400, false)
  })

  it('저장 도구가 성공하면 저장 알림음을 낸다', async () => {
    const t = await listening(
      setup({
        sendAudioTurn: vi.fn(async (_id, _audio, onEvent) => {
          for (const event of reply([
            { type: 'tool', phase: 'end', tool_use_id: 'x', name: 'save_note', input: null, summary: null, is_error: false, notice: null },
          ])) {
            onEvent(event)
          }
        }),
      }),
    )
    speech(t)
    await flush()
    expect(t.out.playEffect).toHaveBeenCalledWith('saved')
  })

  it('말 없음 같은 JSON 오류는 알리고 다시 듣는다(사용자 말풍선은 만들지 않는다)', async () => {
    const t = await listening(
      setup({
        sendAudioTurn: vi.fn(async () => {
          throw new ApiError('no_speech', '말소리가 들리지 않았어요.', 422)
        }),
      }),
    )
    speech(t)
    await flush()
    expect(t.actions).toContainEqual({ type: 'failed', message: '말소리를 듣지 못했어요. 다시 말해 주세요.' })
    expect(t.last()?.name).toBe('listening')
    expect(t.actions.filter((a) => (a as { type: string }).type === 'event')).toEqual([])
  })

  it('서버에 닿지 않으면 알리고 다시 듣는다(M3은 오프라인 보관이 없다)', async () => {
    const t = await listening(
      setup({
        sendAudioTurn: vi.fn(async () => {
          throw new ApiError('network_error', '서버에 연결할 수 없어요.', 0)
        }),
      }),
    )
    speech(t)
    await flush()
    expect(t.last()?.name).toBe('listening')
    expect(t.actions).toContainEqual(expect.objectContaining({ type: 'failed' }))
  })

  it('서버가 이미 끝낸 대화(session_ended)면 정리로 간다', async () => {
    const t = await listening(
      setup({
        sendAudioTurn: vi.fn(async () => {
          throw new ApiError('session_ended', '이미 끝난 대화예요.', 409)
        }),
      }),
    )
    speech(t)
    await flush()
    expect(t.deps.endSession).toHaveBeenCalled()
  })
})

describe('끼어들기', () => {
  it('말하는 중 큰 버튼: 재생을 멈추고 요청을 끊고 들려준 문장까지만 남긴다', async () => {
    const t = await listening(
      setup({
        sendAudioTurn: vi.fn(async (_id, _audio, onEvent, signal) => {
          for (const event of reply().slice(0, 4)) onEvent(event) // done 전
          await new Promise<void>((resolve) => signal?.addEventListener('abort', () => resolve()))
        }),
      }),
    )
    speech(t)
    await flush()
    t.played({ type: 'sentence_played', index: 0 })
    t.controller.tap()
    await flush()
    expect(t.out.stop).toHaveBeenCalled()
    expect(t.actions).toContainEqual({ type: 'interrupt', turnId: 'a1', lastPlayed: 0 })
    expect(t.last()?.name).toBe('listening')
  })

  it('인사말은 끼어들어도 자르지 않는다', async () => {
    const t = setup()
    t.controller.tap()
    await flush()
    t.controller.tap() // 인사말 재생 중 끼어들기
    await flush()
    expect(t.out.stop).toHaveBeenCalled()
    expect(t.actions.some((a) => (a as { type: string }).type === 'interrupt')).toBe(false)
    expect(t.last()?.name).toBe('listening')
  })
})

describe('종료', () => {
  it('대화종료 버튼은 확인 창만 열고, 계속하면 닫는다', async () => {
    const t = await listening()
    t.controller.requestEnd()
    expect(t.last()?.endConfirmOpen).toBe(true)
    t.controller.cancelEnd()
    expect(t.last()?.endConfirmOpen).toBe(false)
    expect(t.deps.endSession).not.toHaveBeenCalled()
    expect(t.last()?.name).toBe('listening')
  })

  it('확인하면 끝내기를 불러 마무리 멘트를 올리고 소리를 재생한 뒤 대기로 간다', async () => {
    const t = await listening()
    t.controller.requestEnd()
    t.controller.confirmEnd()
    await flush()
    expect(t.deps.endSession).toHaveBeenCalledWith('s1', expect.anything())
    expect(t.actions).toContainEqual({ type: 'ending' })
    expect(t.actions).toContainEqual({ type: 'ended', closing: '오늘도 즐거웠어요!' })
    expect(t.closed).toEqual([['s1', { closing: '오늘도 즐거웠어요!', saved: { idea: 1, todo: 0, memo: 0 }, journalStatus: 'pending' }]])
    expect(t.out.enqueue).toHaveBeenLastCalledWith({ audio: 'Q0xPU0U=', index: null, speechText: null })
    expect(t.input.stop).toHaveBeenCalled() // 마이크를 끈다
    expect(t.last()?.name).toBe('idle')
  })

  it('종료가 진행 중인 턴과 부딪쳐 거절되면 잠깐 뒤 다시 부른다', async () => {
    let calls = 0
    const t = await listening(
      setup({
        endSession: vi.fn(async () => {
          calls += 1
          if (calls === 1) throw new ApiError('turn_in_progress', '답변을 만드는 중이에요.', 409)
          return {
            session: STARTED.session,
            closing: '끝!',
            closing_audio: null,
            saved: { idea: 0, todo: 0, memo: 0 },
            journal_status: null,
          } as never
        }),
      }),
    )
    vi.useFakeTimers() // 준비(실제 타이머로 flush)를 마친 뒤에 켠다
    t.controller.longPress()
    await vi.advanceTimersByTimeAsync(0)
    expect(calls).toBe(1)
    expect(t.last()?.name).toBe('closing') // 아직 재시도를 기다리는 중
    await vi.advanceTimersByTimeAsync(600)
    expect(calls).toBe(2)
    expect(t.last()?.name).toBe('idle')
    // 소리가 없으면 마무리 멘트를 기기 TTS용 글로 넘긴다
    expect(t.out.enqueue).toHaveBeenLastCalledWith({ audio: null, index: null, speechText: '끝!' })
  })

  it('정리 중 길게 누르면(그만 기다리기) 응답을 기다리지 않고 대기로 간다', async () => {
    const t = await listening(
      setup({ endSession: vi.fn(() => new Promise<never>(() => {})) }), // 응답이 오지 않는다
    )
    t.controller.longPress()
    await flush()
    expect(t.last()?.name).toBe('closing')
    t.controller.longPress()
    expect(t.last()?.name).toBe('idle')
    expect(t.actions).toContainEqual({ type: 'ended' })
  })

  it('끝내기 요청이 실패하면 알리고 대기로 간다', async () => {
    const t = await listening(
      setup({
        endSession: vi.fn(async () => {
          throw new ApiError('network_error', '서버에 연결할 수 없어요.', 0)
        }),
      }),
    )
    t.controller.longPress()
    await flush()
    expect(t.last()?.name).toBe('idle')
    expect(t.actions).toContainEqual({ type: 'failed', message: '서버에 연결할 수 없어요. 연결을 확인하고 다시 말해 주세요.' })
  })

  it('마이크 오류는 대화를 마치고 정리가 끝난 뒤 이유를 보인다', async () => {
    const t = await listening()
    t.heard({ type: 'error', code: 'mic_denied' })
    await flush()
    expect(t.deps.endSession).toHaveBeenCalled()
    expect(t.last()?.name).toBe('idle')
    const failed = t.actions.filter((a) => (a as { type: string }).type === 'failed')
    expect(failed.at(-1)).toMatchObject({ message: expect.stringContaining('마이크 권한') })
    // 이유는 정리(ended) 뒤에 나온다
    const types = t.actionTypes()
    expect(types.lastIndexOf('failed')).toBeGreaterThan(types.lastIndexOf('ended'))
  })

  it('무발화 시간이 지나면 정리로 간다', async () => {
    vi.useFakeTimers() // 처음부터 가짜 타이머로 돌려 듣기 진입 때 세운 타이머를 움직인다
    const t = setup()
    t.controller.tap()
    await vi.advanceTimersByTimeAsync(0)
    t.played({ type: 'playback_idle' })
    await vi.advanceTimersByTimeAsync(0)
    expect(t.last()?.name).toBe('listening')
    await vi.advanceTimersByTimeAsync(29 * 60_000)
    expect(t.deps.endSession).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(60_000 + 10)
    expect(t.deps.endSession).toHaveBeenCalled() // 30분(서버 설정값 idle_timeout_minutes)
  })
})

describe('음성 대화 중 글 입력', () => {
  it('듣는 중에는 받아 글 턴으로 보내고 내 말풍선을 바로 그린다', async () => {
    const t = await listening()
    expect(t.controller.sendText('글로 보낼게')).toBe(true)
    await flush()
    expect(t.deps.sendTextTurn).toHaveBeenCalledWith('s1', '글로 보낼게', expect.any(Function), expect.anything())
    expect(t.actions).toContainEqual(expect.objectContaining({ type: 'send', text: '글로 보낼게' }))
    expect(t.deps.sendAudioTurn).not.toHaveBeenCalled()
  })

  it('듣는 중이 아니면(처리 중·말하기·대기) 받지 않는다', async () => {
    const idle = setup()
    expect(idle.controller.sendText('안 돼')).toBe(false)
    const t = await listening(
      setup({ sendAudioTurn: vi.fn(() => new Promise<never>(() => {})) }), // 답변이 오지 않는다
    )
    speech(t)
    await flush()
    expect(t.last()?.name).toBe('processing')
    expect(t.controller.sendText('안 돼')).toBe(false)
  })

  it('서버가 받기 전에 실패하면 말풍선을 빼고 글을 돌려준다', async () => {
    const t = await listening(
      setup({
        sendTextTurn: vi.fn(async (_id, _text, onEvent) => {
          onEvent({ type: 'error', code: 'internal_error', message: '서버 내부 오류가 발생했습니다.' })
        }),
      }),
    )
    const unsent = vi.fn()
    t.controller.sendText('다시 줘', unsent)
    await flush()
    expect(unsent).toHaveBeenCalledWith('다시 줘')
    expect(t.actions).toContainEqual(expect.objectContaining({ type: 'unsend' }))
  })
})

describe('다시 열기와 정리', () => {
  it('다시 연 대화는 시작 요청 없이 그 응답으로 이어 간다', async () => {
    const t = setup()
    const reopened: SessionReopened = {
      ...STARTED,
      turns: [
        { id: 'g1', seq: 0, role: 'assistant', text: '다시 왔네요', interrupted: false, merged_from: null, created_at: '2026-10-30T00:00:00Z', attachments: [] },
      ],
    }
    expect(t.controller.resume(reopened)).toBe(true)
    await flush()
    expect(t.deps.startSession).not.toHaveBeenCalled()
    expect(t.actions).toContainEqual(expect.objectContaining({ type: 'resumed', sessionId: 's1', personaName: '제니' }))
    expect(t.out.enqueue).toHaveBeenCalledWith({ audio: 'R1JFRVQ=', index: null, speechText: null })
    t.played({ type: 'playback_idle' })
    await flush()
    expect(t.last()?.name).toBe('listening')
  })

  it('대기 중이 아니면 다시 열기를 받지 않는다', async () => {
    const t = await listening()
    expect(t.controller.resume({ ...STARTED, turns: [] })).toBe(false)
  })

  it('dispose는 재생을 멈추고 요청을 끊고 마이크를 정리한다', async () => {
    const t = await listening()
    await t.controller.dispose()
    expect(t.out.stop).toHaveBeenCalled()
    expect(t.out.dispose).toHaveBeenCalled()
    expect(t.input.dispose).toHaveBeenCalled()
    t.controller.tap() // 정리 뒤에는 아무 일도 하지 않는다
    expect(t.states.length).toBeGreaterThan(0)
  })
})

describe('처리 중에 한 말(큐) — 리뷰 지적 회귀', () => {
  /** 첫 턴 요청은 gate를 열 때까지 기다리고, 그동안 한 말은 큐에 쌓인다 */
  function gated(second: VoiceDeps['sendAudioTurn']) {
    let open: () => void = () => {}
    const gate = new Promise<void>((resolve) => (open = resolve))
    let calls = 0
    const sendAudioTurn = vi.fn<VoiceDeps['sendAudioTurn']>(async (id, audio, onEvent, signal) => {
      calls += 1
      if (calls === 1) {
        await gate
        for (const event of reply()) onEvent(event)
        return
      }
      return second(id, audio, onEvent, signal)
    })
    return { sendAudioTurn, open: () => open() }
  }

  it('답변을 기다리며 한 말은 답변을 다 들려준 뒤 이어서 보낸다', async () => {
    const g = gated(async (_id, _audio, onEvent) => {
      for (const event of reply().map((e) => (e.type === 'turn' ? { ...e, turn_id: 'a2' } : e))) onEvent(event as never)
    })
    const t = await listening(setup({ sendAudioTurn: g.sendAudioTurn }))
    speech(t)
    await flush()
    expect(t.last()?.name).toBe('processing')
    speech(t) // 처리 중에 이어서 한 말
    await flush()
    expect(t.last()?.queued).toBe(1)
    expect(g.sendAudioTurn).toHaveBeenCalledTimes(1)
    g.open()
    await flush()
    t.played({ type: 'sentence_played', index: 0 })
    t.played({ type: 'sentence_played', index: 1 })
    t.played({ type: 'playback_idle' })
    await flush()
    expect(g.sendAudioTurn).toHaveBeenCalledTimes(2) // 큐의 말을 보통 턴으로 보냈다
    expect(t.last()?.queued).toBe(0)
  })

  it('큐에서 꺼낸 말이 인식되지 않아도(no_speech) 멈추지 않고 다시 듣는다', async () => {
    const g = gated(async () => {
      throw new ApiError('no_speech', '말소리가 들리지 않았어요.', 422)
    })
    const t = await listening(setup({ sendAudioTurn: g.sendAudioTurn }))
    speech(t)
    await flush()
    speech(t)
    await flush()
    g.open()
    await flush()
    t.played({ type: 'sentence_played', index: 0 })
    t.played({ type: 'sentence_played', index: 1 })
    t.played({ type: 'playback_idle' })
    await flush()
    // 예전에는 queued가 1로 남아 sendQueued↔turn_error가 동기로 끝없이 돌았다
    expect(g.sendAudioTurn).toHaveBeenCalledTimes(2)
    expect(t.last()?.name).toBe('listening')
    expect(t.last()?.queued).toBe(0)
  })

  it('큐에서 꺼낸 말이 서버에 닿지 않아도 큐 수를 맞추고 다시 듣는다', async () => {
    const g = gated(async () => {
      throw new ApiError('network_error', '서버에 연결할 수 없어요.', 0)
    })
    const t = await listening(setup({ sendAudioTurn: g.sendAudioTurn }))
    speech(t)
    await flush()
    speech(t)
    await flush()
    g.open()
    await flush()
    t.played({ type: 'playback_idle' })
    await flush()
    expect(t.last()?.name).toBe('listening')
    expect(t.last()?.queued).toBe(0)
    expect(t.actions).toContainEqual(expect.objectContaining({ type: 'failed' }))
  })
})

describe('요청 시간 제한(규약 6.6: 시간 초과도 실패 이벤트로 끝낸다)', () => {
  it('시작 요청이 응답하지 않으면 30초 뒤 시작 실패로 대기에 돌아간다', async () => {
    vi.useFakeTimers()
    const t = setup({ startSession: vi.fn(() => new Promise<never>(() => {})) })
    t.controller.tap()
    await vi.advanceTimersByTimeAsync(29_000)
    expect(t.last()?.name).toBe('processing')
    await vi.advanceTimersByTimeAsync(2_000)
    expect(t.last()?.name).toBe('idle')
    expect(t.actions).toContainEqual({ type: 'failed', message: '서버가 응답하지 않아요. 다시 해 주세요.' })
  })

  it('턴이 시작되기(turn 이벤트) 전에 30초가 지나면 오류로 알리고 다시 듣는다', async () => {
    const t = await listening(setup({ sendAudioTurn: vi.fn(() => new Promise<never>(() => {})) }))
    vi.useFakeTimers()
    speech(t)
    await vi.advanceTimersByTimeAsync(31_000)
    expect(t.last()?.name).toBe('listening')
    expect(t.actions).toContainEqual({ type: 'failed', message: '서버가 응답하지 않아요. 다시 해 주세요.' })
  })

  it('끝내기 요청이 응답하지 않으면 60초 뒤 실패로 대기에 돌아간다', async () => {
    const t = await listening(setup({ endSession: vi.fn(() => new Promise<never>(() => {})) }))
    vi.useFakeTimers()
    t.controller.longPress()
    await vi.advanceTimersByTimeAsync(59_000)
    expect(t.last()?.name).toBe('closing')
    await vi.advanceTimersByTimeAsync(2_000)
    expect(t.last()?.name).toBe('idle')
    expect(t.actions).toContainEqual({ type: 'failed', message: '서버가 응답하지 않아요. 다시 해 주세요.' })
  })

  it('서버 설정값을 받는 요청이 멈춰도 5초 뒤 기본값으로 마이크를 켠다', async () => {
    vi.useFakeTimers()
    const t = setup({ getProfile: vi.fn(() => new Promise<never>(() => {})) })
    t.controller.tap()
    await vi.advanceTimersByTimeAsync(0)
    t.played({ type: 'playback_idle' })
    await vi.advanceTimersByTimeAsync(0)
    expect(t.input.start).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(5_100)
    expect(t.input.start).toHaveBeenCalled()
  })
})

describe('그 밖의 리뷰 지적 회귀', () => {
  it('끝난 대화에 늦게 온 마이크 오류는 무시하고 다음 대화에 이유를 남기지 않는다', async () => {
    const t = await listening()
    t.controller.longPress() // 정상 종료
    await flush()
    expect(t.last()?.name).toBe('idle')
    t.heard({ type: 'error', code: 'mic_denied' }) // 늦게 온 오류(규약 6.3: 무시)
    await flush()
    t.controller.tap()
    await flush()
    t.played({ type: 'playback_idle' })
    await flush()
    t.controller.longPress()
    await flush()
    const failed = t.actions.filter((a) => (a as { type: string }).type === 'failed')
    expect(JSON.stringify(failed)).not.toContain('마이크 권한')
  })

  it('끼어든 직후 서버가 이전 답변을 정리 중이라 거절하면 0.5초 뒤 다시 보낸다(음성)', async () => {
    let calls = 0
    const t = await listening(
      setup({
        sendAudioTurn: vi.fn(async (_id, _audio, onEvent) => {
          calls += 1
          if (calls === 1) throw new ApiError('turn_in_progress', '답변을 만드는 중이에요.', 409)
          for (const event of reply()) onEvent(event)
        }),
      }),
    )
    vi.useFakeTimers()
    speech(t)
    await vi.advanceTimersByTimeAsync(0)
    expect(calls).toBe(1)
    await vi.advanceTimersByTimeAsync(600)
    expect(calls).toBe(2)
    expect(t.out.enqueue).toHaveBeenCalledWith({ audio: 'QQ==', index: 0, speechText: null })
    expect(t.actions.some((a) => (a as { type: string; message?: string }).message?.includes('문제'))).toBe(false)
  })

  it('거절이 계속되면 3번까지만 다시 보내고 알린다', async () => {
    const t = await listening(
      setup({
        sendAudioTurn: vi.fn(async () => {
          throw new ApiError('turn_in_progress', '답변을 만드는 중이에요.', 409)
        }),
      }),
    )
    vi.useFakeTimers()
    speech(t)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(t.deps.sendAudioTurn).toHaveBeenCalledTimes(4) // 처음 + 다시 3번
    expect(t.last()?.name).toBe('listening')
    expect(t.actions).toContainEqual(expect.objectContaining({ type: 'failed' }))
  })

  it('마이크를 켜기 전에 정리로 가면 마이크가 켜진 채 남지 않는다', async () => {
    let profile: (value: never) => void = () => {}
    const t = setup({ getProfile: vi.fn(() => new Promise<never>((resolve) => (profile = resolve))) })
    t.controller.tap()
    await flush()
    t.played({ type: 'playback_idle' }) // 듣기 진입: micOn은 프로필을 기다리는 중
    await flush()
    t.controller.longPress() // 정리로: micOff
    await flush()
    profile({ client: { vad: { speech_threshold: 0.5, silence_threshold: 0.25, playback_speech_threshold: 0.8, playback_silence_threshold: 0.65, end_of_speech_silence_ms: 1800, min_speech_ms: 300 }, session: { idle_timeout_minutes: 30 } } } as never)
    await flush()
    expect(t.input.start).not.toHaveBeenCalled()
  })

  it('대화를 시작하는 중에 종료가 오면 요청을 끊고 대기로 간다', async () => {
    let signal: AbortSignal | undefined
    const t = setup({
      startSession: vi.fn((_mode, s) => {
        signal = s
        return new Promise<never>(() => {})
      }),
    })
    t.controller.tap()
    await flush()
    t.controller.longPress()
    await flush()
    expect(signal?.aborted).toBe(true)
    expect(t.last()?.name).toBe('idle')
  })
})
