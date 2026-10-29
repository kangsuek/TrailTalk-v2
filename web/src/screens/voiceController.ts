// 음성 대화 컨트롤러(클라이언트 규약 6.6 "플랫폼이 지킬 것", 계획 M3-13).
// 상태 머신(core/sessionMachine)에 이벤트를 넣고, 나온 명령을 마이크(AudioInput)·재생(AudioOutput)·
// 서버 API로 실행한다. 말풍선은 글 대화와 같은 리듀서(core/conversation)로 그린다.
//
// M3 범위: 시작·말하기·답변 재생·끼어들기(턴 요청 연결 끊기)·종료 확인·글 입력·다시 열기.
// 쉬기 버튼·오프라인 보관(IndexedDB)·맞장구·병합·서버 끼어들기 API는 M4다. 처리 중에 한 말은 메모리 큐에
// 두었다가 답변 뒤에 차례로 보낸다(머신의 이어 말하기 전이, 새로고침하면 사라진다).
import {
  ApiError,
  endSession,
  reportLatency,
  sendAudioTurn,
  sendTurn as sendTextTurn,
  startSession,
  type SessionClosed,
  type SessionReopened,
  type SessionStarted,
} from '../api/conversation.ts'
import { getProfile } from '../api/profile.ts'
import {
  DEFAULT_SESSION_CONFIG,
  DEFAULT_VAD_SETTINGS,
  createLatencyTracker,
  initialSession,
  transition,
  vadSettingsFrom,
  type AudioInput,
  type AudioInputEvent,
  type AudioOutput,
  type AudioOutputEvent,
  type RecordedAudio,
  type SessionCommand,
  type SessionConfig,
  type SessionEvent,
  type SessionState,
  type VadSettings,
} from '../core/index.ts'
import type { ConversationAction, StreamEvent } from '../core/conversation.ts'
import listenSound from '../../../shared/sounds/listen.mp3'
import savedSound from '../../../shared/sounds/saved.mp3'
import { lazyAudioInput, lazyAudioOutput } from './lazyPlatform.ts'

export interface VoiceDeps {
  createInput: (settings: VadSettings, onEvent: (event: AudioInputEvent) => void) => AudioInput
  createOutput: (onEvent: (event: AudioOutputEvent) => void) => AudioOutput
  startSession: typeof startSession
  sendAudioTurn: typeof sendAudioTurn
  sendTextTurn: typeof sendTextTurn // 음성 대화 중 글로 보낸 말(서버가 답변 음성도 만든다)
  reportLatency: typeof reportLatency
  endSession: typeof endSession
  getProfile: typeof getProfile
  now: () => number // 지연 측정 시계(단조 ms, 말 끝 시각과 같은 기준)
}

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms))

/** promise를 ms까지만 기다린다(넘으면 거절). 타이머는 끝나면 치운다 */
function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  let timer: ReturnType<typeof setTimeout> | undefined
  const limit = new Promise<never>((_, reject) => {
    timer = setTimeout(() => reject(new Error('timeout')), ms)
  })
  return Promise.race([promise, limit]).finally(() => clearTimeout(timer))
}

/** 취소 신호가 오면 요청이 신호를 무시해도 바로 거절한다(시간 제한·끼어들기·종료가 요청에 막히지 않게) */
function raceAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) return Promise.reject(new Error('aborted'))
  return new Promise<T>((resolve, reject) => {
    const onAbort = () => reject(new Error('aborted'))
    signal.addEventListener('abort', onAbort, { once: true })
    promise.then(resolve, reject).finally(() => signal.removeEventListener('abort', onAbort))
  })
}

const DEFAULT_DEPS: VoiceDeps = {
  createInput: lazyAudioInput,
  // offline 알림음은 M4(오프라인 큐)에서 연결한다
  createOutput: (onEvent) => lazyAudioOutput(onEvent, { listen: listenSound, saved: savedSound }),
  startSession,
  sendAudioTurn,
  sendTextTurn,
  reportLatency,
  endSession,
  getProfile,
  now: () => performance.now(),
}

// 진행 중이던 턴이 아직 정리되지 않아 서버가 거절할 때(`turn_in_progress`) 다시 보내는 횟수와 간격(규약 6.3·6.6)
const BUSY_RETRIES = 3
const BUSY_RETRY_MS = 500
// 요청 시간 제한(규약 6.6: 시간 초과도 실패 이벤트로 끝낸다). 서버는 끝내기에서 일지 정리를 최대 45초 기다린다
const START_TIMEOUT_MS = 30_000
const PRE_TURN_TIMEOUT_MS = 30_000 // 턴이 시작되기(turn 이벤트) 전까지
const END_TIMEOUT_MS = 60_000
const PROFILE_TIMEOUT_MS = 5_000 // 서버 설정값을 못 받으면 기본값으로 쓴다

// 세션이 서버에서 이미 끝났다는 오류(머신이 정리로 간다)
const SESSION_GONE = new Set(['session_ended', 'session_not_found'])

const ERROR_MESSAGES: Record<string, string> = {
  mic_denied: '마이크 권한이 없어요. 브라우저 설정에서 마이크를 허용한 뒤 다시 시작해 주세요.',
  mic_unavailable: '마이크를 쓸 수 없어요. HTTPS로 접속했는지, 마이크가 연결돼 있는지 확인해 주세요.',
  vad_failed: '음성 감지를 시작하지 못했어요. 글로 대화해 주세요.',
  no_speech: '말소리를 듣지 못했어요. 다시 말해 주세요.',
  network_error: '서버에 연결할 수 없어요. 연결을 확인하고 다시 말해 주세요.',
  timeout: '서버가 응답하지 않아요. 다시 해 주세요.',
  stream_closed: '답변을 받는 중에 연결이 끊겼어요.',
}

export interface VoiceClosed {
  closing: string
  saved: SessionClosed['saved']
  journalStatus: SessionClosed['journal_status']
}

export interface VoiceController {
  /** 큰 버튼 한 번(시작·끼어들기·쉬기 재개). 사용자 동작 안에서 불러야 소리가 난다 */
  tap(): void
  /** 대화종료 버튼: 확인 창을 연다(상태는 그대로) */
  requestEnd(): void
  /** 확인 창의 "끝내고 정리하기" */
  confirmEnd(): void
  /** 확인 창의 "계속 대화하기" */
  cancelEnd(): void
  /** 길게 누르기(보조 종료). 정리 중에는 "그만 기다리기"(응답을 기다리지 않고 대기로 간다) */
  longPress(): void
  /** 일지 상세에서 다시 연 대화(reopen {mode: voice} 응답)를 이어서 한다. 대기 중일 때만 받는다 */
  resume(reopened: SessionReopened): boolean
  /**
   * 음성 대화 중 글로 보낸 말. 듣는 중에만 받는다. 받지 못하면 false. 서버가 받기 전에 실패하면
   * onUnsent로 글을 돌려준다
   */
  sendText(text: string, onUnsent?: (text: string) => void): boolean
  dispose(): Promise<void>
}

export function createVoiceController({
  dispatch,
  onState,
  onClosed,
  deps = {},
}: {
  dispatch: (action: ConversationAction) => void
  onState: (state: SessionState) => void
  /** 끝내기 응답을 받았다(마무리 멘트·저장 개수). 정리 중 "그만 기다리기"로 끝낸 대화에는 오지 않는다 */
  onClosed?: (sessionId: string, closed: VoiceClosed) => void
  deps?: Partial<VoiceDeps>
}): VoiceController {
  const d = { ...DEFAULT_DEPS, ...deps }
  let state = initialSession
  let config: SessionConfig = DEFAULT_SESSION_CONFIG
  let vad: VadSettings = DEFAULT_VAD_SETTINGS
  let input: AudioInput | null = null // 처음 마이크를 쓸 때 만든다(서버 설정값을 받은 뒤)
  let inputPending: Promise<AudioInput | null> | null = null
  let micWanted = false // 마이크를 켜 두려는 의도(켜기 요청이 비동기라 그사이 꺼도 켜진 채 남지 않게)
  let sessionId: string | null = null
  let reopened: SessionReopened | null = null // 다시 연 대화를 이어 가는 시작(시작 요청 대신 이 응답을 쓴다)
  let startAbort: AbortController | null = null
  let turnAbort: AbortController | null = null
  let endAbort: AbortController | null = null
  let greetingTurn: string | null = null // 인사말 턴(문장 번호 없이 재생하므로 끼어들어도 자르지 않는다)
  let idleTimer: ReturnType<typeof setTimeout> | undefined
  let closingReason: string | null = null // 대화가 끝난 이유(정리가 끝난 뒤 보인다)
  let disposed = false
  const latency = createLatencyTracker(d.now)

  // 말 한 번(음성)·글 하나를 머신의 utteranceId로 보관한다. 처리 중에 한 말은 큐에 쌓였다가 차례로 나간다
  type Utterance =
    | { kind: 'audio'; audio: RecordedAudio; speechEndedAt: number }
    | { kind: 'text'; text: string; onUnsent?: (text: string) => void }
  const utterances = new Map<string, Utterance>()
  const queue: string[] = [] // 큐에 넣은 utteranceId(오래된 것부터)
  let nextUtterance = 0

  // 명령 실행 중에 이벤트가 또 생길 수 있어(같은 흐름) 차례로 처리한다
  const pending: SessionEvent[] = []
  let processing = false

  const send = (event: SessionEvent) => {
    if (disposed) return
    pending.push(event)
    if (processing) return
    processing = true
    try {
      while (pending.length > 0) {
        const next = pending.shift()!
        const previous = state
        const result = transition(state, next, config)
        state = result.state
        if (state !== previous) onState(state)
        // 정리 중 길게 누르기("그만 기다리기"): 끝내기 응답을 기다리지 않고 대기로 간다(서버 끝내기는 멱등)
        if (previous.name === 'closing' && state.name === 'idle' && next.type === 'long_press') {
          endAbort?.abort()
          dispatch({ type: 'ended' })
          showClosingReason()
        }
        for (const command of result.commands) run(command)
        if (previous.name !== 'idle' && state.name === 'idle') {
          // 대화가 끝났다(정상·끝내기 실패·시작 실패): 이 대화의 남은 말과 타이머를 정리한다
          sessionId = null
          queue.length = 0
          utterances.clear()
          latency.cancel()
          clearTimeout(idleTimer)
        }
      }
    } finally {
      processing = false
    }
  }

  const output = d.createOutput((event) => {
    if (event.type === 'started') return onPlaybackStarted()
    send(event)
  })

  const onPlaybackStarted = () => {
    const report = latency.playbackStarted(false) // 검색 안내 음성은 M5
    if (report === null || sessionId === null) return
    void d
      .reportLatency(
        sessionId,
        report.turnId,
        report.speechToRequestMs,
        report.requestToPlaybackMs,
        report.firstSoundNotice,
      )
      .catch(() => {}) // 기다리지 않고 실패는 무시한다
  }

  const messageOf = (error: unknown, code: string): string =>
    ERROR_MESSAGES[code] ?? (error instanceof ApiError ? error.message : '문제가 생겼어요. 다시 해 주세요.')

  const showClosingReason = () => {
    if (closingReason === null) return
    dispatch({ type: 'failed', message: closingReason })
    closingReason = null
  }

  const ensureInput = (): Promise<AudioInput | null> => {
    if (input) return Promise.resolve(input)
    inputPending ??= (async () => {
      try {
        const client = (await withTimeout(d.getProfile(), PROFILE_TIMEOUT_MS)).client
        vad = vadSettingsFrom(client.vad)
        config = { idleTimeoutMinutes: client.session.idle_timeout_minutes }
      } catch {
        // 서버 설정값을 못 받거나 늦으면 기본값으로 쓴다
      }
      if (disposed) return null // 기다리는 사이 정리됐으면 마이크를 만들지 않는다(닫을 길이 없다)
      input = d.createInput(vad, onInputEvent)
      return input
    })()
    return inputPending
  }

  const onInputEvent = (event: AudioInputEvent) => {
    if (event.type === 'speech_start') return send({ type: 'speech_start' })
    if (event.type === 'speech_end') {
      const id = `u${(nextUtterance += 1)}`
      utterances.set(id, { kind: 'audio', audio: event.audio, speechEndedAt: event.speechEndedAt })
      return send({ type: 'speech_end', utteranceId: id })
    }
    // 마이크 오류: 대화를 마치고(일지 정리) 정리가 끝난 뒤 이유를 보인다(규약 6.3).
    // 대기·정리 중에 늦게 온 오류는 무시한다(이유가 다음 대화로 새지 않게)
    if (state.name === 'idle' || state.name === 'closing') return
    closingReason = ERROR_MESSAGES[event.code] ?? ERROR_MESSAGES.vad_failed
    send({ type: 'long_press' })
  }

  /** 시작 응답(또는 다시 연 응답)의 인사말을 화면에 올리고 소리를 재생한다 */
  const beginGreeting = (
    started: Pick<SessionStarted, 'session' | 'greeting' | 'persona'>,
    turns: SessionReopened['turns'] | null,
  ) => {
    sessionId = started.session.id
    greetingTurn = started.greeting.turn_id
    if (turns === null) {
      dispatch({
        type: 'started',
        sessionId: started.session.id,
        personaName: started.persona.name,
        greeting: { turnId: started.greeting.turn_id, text: started.greeting.text },
      })
    } else {
      dispatch({
        type: 'resumed',
        sessionId: started.session.id,
        personaName: started.persona.name,
        turns,
      })
    }
    send({ type: 'session_started', turnId: started.greeting.turn_id })
    // 소리가 없으면(합성 실패) 글을 기기 TTS로 읽고, 그것도 없으면 바로 playback_idle이 온다
    output.enqueue({
      audio: started.greeting.audio,
      index: null,
      speechText: started.greeting.audio ? null : started.greeting.text,
    })
  }

  const takeTurn = (id: string): Utterance | null => {
    const utterance = utterances.get(id) ?? null
    utterances.delete(id)
    return utterance
  }

  /** 서버에서 온 이벤트를 화면과 머신에 반영한다. 소리는 대기열에 넣은 뒤에 머신에 알린다(규약 6.6) */
  const onStreamEvent = (event: StreamEvent, turn: { gotTurn: boolean; id: string | null }) => {
    if (event.type === 'turn') {
      turn.gotTurn = true
      turn.id = event.turn_id
      latency.attach(event.turn_id)
      dispatch({ type: 'event', event })
      send({ type: 'turn', turnId: event.turn_id })
    } else if (event.type === 'sentence') {
      output.enqueue({
        audio: event.audio,
        index: event.index,
        speechText: event.audio ? null : event.speech_text,
      })
      dispatch({ type: 'event', event })
      if (turn.id) send({ type: 'sentence', turnId: turn.id, index: event.index })
    } else if (event.type === 'done') {
      dispatch({ type: 'event', event })
      send({ type: 'turn_done', turnId: event.turn_id, sessionStatus: event.session_status })
    } else if (event.type === 'error') {
      latency.cancel()
      dispatch({ type: 'event', event })
      send({ type: 'turn_error', turnId: turn.gotTurn ? turn.id : null, code: event.code })
    } else {
      if (event.type === 'tool' && event.phase === 'end' && event.name === 'save_note' && !event.is_error) {
        send({ type: 'note_saved' })
      }
      dispatch({ type: 'event', event })
    }
  }

  const runTurn = async (utteranceId: string, fromQueue: boolean) => {
    const utterance = takeTurn(utteranceId)
    const id = sessionId
    if (utterance === null || id === null) {
      // 큐에서 꺼낼 말이 없다: 머신의 큐 수를 0으로 맞춰야 sendQueued ↔ turn_error가 끝없이 돌지 않는다
      if (fromQueue) send({ type: 'queue_sent', remaining: queue.length })
      send({ type: 'turn_error', turnId: null, code: 'queue_empty' })
      return
    }
    // 큐에서 꺼낸 말은 서버가 받았거나(turn) 실패하면(이미 큐에서 뺐다) 머신의 큐 수를 맞춘다
    let queueSettled = false
    const settleQueue = () => {
      if (!fromQueue || queueSettled) return
      queueSettled = true
      send({ type: 'queue_sent', remaining: queue.length })
    }
    const textId = `t${utteranceId}`
    if (utterance.kind === 'audio') latency.begin(utterance.speechEndedAt)
    else {
      latency.cancel() // 글 턴은 지연을 재지 않는다
      dispatch({ type: 'send', id: textId, text: utterance.text })
    }
    for (let attempt = 0; ; attempt += 1) {
      const controller = (turnAbort = new AbortController())
      const turn = { gotTurn: false, id: null as string | null }
      let timedOut = false
      let busy = false // 서버가 이전 답변을 정리 중이라 거절했다(다시 보낸다)
      const preTurn = setTimeout(() => {
        timedOut = true
        controller.abort()
      }, PRE_TURN_TIMEOUT_MS)
      try {
        const handle = (event: StreamEvent) => {
          if (controller.signal.aborted) return
          if (event.type === 'turn') clearTimeout(preTurn)
          if (event.type === 'error' && !turn.gotTurn && event.code === 'turn_in_progress' && attempt < BUSY_RETRIES) {
            busy = true
            return
          }
          // turn 전의 오류는 서버가 메시지를 받지 못한 것이다: 글은 입력창으로 돌려주고 말풍선을 뺀다
          if (event.type === 'error' && !turn.gotTurn && utterance.kind === 'text') {
            dispatch({ type: 'unsend', id: textId })
            utterance.onUnsent?.(utterance.text)
          }
          if (event.type === 'turn' || (event.type === 'error' && !turn.gotTurn)) settleQueue()
          onStreamEvent(event, turn)
        }
        const request =
          utterance.kind === 'audio'
            ? d.sendAudioTurn(id, utterance.audio, handle, controller.signal)
            : d.sendTextTurn(id, utterance.text, handle, controller.signal)
        await raceAbort(request, controller.signal)
      } catch (error) {
        if (controller.signal.aborted && !timedOut) return // 끼어들기·종료로 끊었다
        const code = timedOut ? 'timeout' : error instanceof ApiError ? error.code : 'network_error'
        if (code === 'turn_in_progress' && !turn.gotTurn && attempt < BUSY_RETRIES) {
          busy = true
        } else {
          latency.cancel()
          if (utterance.kind === 'text' && !turn.gotTurn) {
            dispatch({ type: 'unsend', id: textId })
            utterance.onUnsent?.(utterance.text)
          }
          if (SESSION_GONE.has(code)) closingReason = messageOf(error, code)
          settleQueue()
          // 서버에 닿지 않았거나 스트림이 끊겼다: M3은 오프라인 보관이 없으므로 알리고 다시 듣는다
          send({ type: 'turn_error', turnId: turn.gotTurn ? turn.id : null, code })
          if (!SESSION_GONE.has(code)) dispatch({ type: 'failed', message: messageOf(error, code) })
          return
        }
      } finally {
        clearTimeout(preTurn)
      }
      if (!busy) return
      // 잠깐 기다렸다 다시 보낸다. 그사이 끼어들기·종료가 오면 그만둔다
      const waiting = (turnAbort = new AbortController())
      await sleep(BUSY_RETRY_MS)
      if (waiting.signal.aborted || disposed) return
    }
  }

  const run = (command: SessionCommand) => {
    switch (command.type) {
      case 'startSession':
        void begin()
        break
      case 'sendTurn':
        void runTurn(command.utteranceId, false)
        break
      case 'queueUtterance':
        queue.push(command.utteranceId) // 처리 중에 한 말: 답변 뒤에 차례로 보낸다
        break
      case 'sendQueued': {
        const next = queue.shift()
        if (next === undefined) {
          send({ type: 'queue_sent', remaining: 0 }) // 큐 수를 맞춘다(끝없이 다시 부르지 않게)
          send({ type: 'turn_error', turnId: null, code: 'queue_empty' })
        } else void runTurn(next, true)
        break
      }
      case 'cancelTurn':
        // 서버 끼어들기 API는 M4다. 턴 요청 연결을 끊으면 서버는 보낸 문장까지를 끊긴 답변으로 남긴다
        turnAbort?.abort()
        latency.cancel()
        if (command.turnId !== greetingTurn) {
          dispatch({ type: 'interrupt', turnId: command.turnId, lastPlayed: command.lastPlayed })
        }
        break
      case 'endSession':
        void finish()
        break
      case 'micOn':
        micWanted = true
        void ensureInput()
          .then((i) => (i && micWanted && !disposed ? i.start() : undefined))
          .catch(() => {}) // 오류는 입력의 error 이벤트로 온다
        break
      case 'micOff':
        micWanted = false // 켜기 요청이 아직 대기 중이어도 켜지지 않게 한다
        void input?.stop()
        break
      case 'setVadMode':
        void ensureInput().then((i) => (i && !disposed ? i.setMode(command.mode) : undefined))
        break
      case 'stopPlayback':
        output.stop()
        break
      case 'playSound':
        if (command.name !== 'offline') output.playEffect(command.name) // 오프라인 알림음은 M4
        break
      case 'notifyError':
        dispatch({ type: 'failed', message: messageOf(null, command.code) })
        break
      case 'startIdleTimer':
        clearTimeout(idleTimer)
        idleTimer = setTimeout(() => send({ type: 'idle_timeout' }), command.minutes * 60_000)
        break
      case 'clearIdleTimer':
        clearTimeout(idleTimer)
        break
      case 'speakOfflineNotice':
        send({ type: 'offline_notice_done' }) // 오프라인 안내는 M4
        break
      case 'showEndConfirm':
      case 'hideEndConfirm':
        break // 화면이 상태의 endConfirmOpen을 보고 확인 창을 연다
    }
  }

  const begin = async () => {
    const controller = (startAbort = new AbortController())
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, START_TIMEOUT_MS)
    closingReason = null // 지난 대화의 이유가 남아 있지 않게
    dispatch({ type: 'start' })
    try {
      if (reopened !== null) {
        const again = reopened
        reopened = null
        beginGreeting(again, again.turns)
        return
      }
      const started = await raceAbort(d.startSession('voice', controller.signal), controller.signal)
      if (controller.signal.aborted) return
      beginGreeting(started, null)
    } catch (error) {
      if (controller.signal.aborted && !timedOut) return // 시작 중에 종료가 와서 끊었다
      const code = timedOut ? 'timeout' : error instanceof ApiError ? error.code : 'network_error'
      send({ type: 'start_failed', code })
      dispatch({ type: 'failed', message: messageOf(error, code) })
    } finally {
      clearTimeout(timer)
    }
  }

  const finish = async () => {
    const id = sessionId
    if (id === null) {
      // 대화를 시작하는 중에 종료가 왔다: 시작 요청을 끊고 조용히 대기로 간다(머신이 정리에 갇히지 않게)
      startAbort?.abort()
      dispatch({ type: 'failed', message: '' })
      send({ type: 'session_closed' })
      return
    }
    turnAbort?.abort() // 받는 중인 답변은 받은 데까지 끊는다
    const controller = (endAbort = new AbortController())
    let timedOut = false
    const timer = setTimeout(() => {
      timedOut = true
      controller.abort()
    }, END_TIMEOUT_MS)
    dispatch({ type: 'ending' })
    try {
      let closed: SessionClosed | null = null
      for (let attempt = 0; closed === null; attempt += 1) {
        try {
          closed = await raceAbort(d.endSession(id, controller.signal), controller.signal)
        } catch (error) {
          // 진행 중이던 턴이 아직 정리되지 않아 거절되면 잠깐 뒤 다시 부른다
          const busy = error instanceof ApiError && error.code === 'turn_in_progress'
          if (!busy || attempt >= BUSY_RETRIES || controller.signal.aborted) throw error
          await sleep(BUSY_RETRY_MS)
        }
      }
      if (controller.signal.aborted) return
      dispatch({ type: 'ended', closing: closed.closing })
      onClosed?.(id, {
        closing: closed.closing,
        saved: closed.saved,
        journalStatus: closed.journal_status,
      })
      // 마무리 멘트를 들려준 뒤 대기로 간다. 소리가 없으면 글을 기기 TTS로 읽는다
      output.enqueue({
        audio: closed.closing_audio,
        index: null,
        speechText: closed.closing_audio ? null : closed.closing,
      })
      send({ type: 'session_closed' })
      showClosingReason()
    } catch (error) {
      if (controller.signal.aborted && !timedOut) return // "그만 기다리기"로 끊었다
      const code = timedOut ? 'timeout' : error instanceof ApiError ? error.code : 'network_error'
      send({ type: 'end_failed', code })
      dispatch({ type: 'failed', message: messageOf(error, code) })
    } finally {
      clearTimeout(timer)
    }
  }

  return {
    tap() {
      // 브라우저가 소리를 내게 하려면 사용자 동작 안에서 오디오를 열어야 한다
      void output.unlock()
      send({ type: 'tap' })
    },
    requestEnd: () => send({ type: 'end_request' }),
    confirmEnd: () => send({ type: 'end_confirm' }),
    cancelEnd: () => send({ type: 'end_cancel' }),
    longPress: () => send({ type: 'long_press' }),
    resume(next) {
      if (state.name !== 'idle') return false
      reopened = next
      void output.unlock()
      send({ type: 'tap' })
      return true
    },
    sendText(text, onUnsent) {
      // 듣는 중에만 받는다. 처리 중·말하기·쉬기·큐가 남은 때는 받지 않는다(화면은 보내기만 잠근다)
      if (state.name !== 'listening' || state.queued > 0) return false
      const id = `u${(nextUtterance += 1)}`
      utterances.set(id, { kind: 'text', text, onUnsent })
      send({ type: 'speech_end', utteranceId: id })
      return true
    },
    async dispose() {
      disposed = true
      clearTimeout(idleTimer)
      startAbort?.abort()
      turnAbort?.abort()
      endAbort?.abort()
      output.stop()
      await Promise.allSettled([input?.dispose(), output.dispose()])
    },
  }
}
