// 음성 대화 세션 상태 머신(클라이언트 규약 6절, 계획 M3-09).
// 이벤트를 받아 다음 상태와 "명령"을 돌려주는 순수 함수다. 마이크·재생·서버 호출·타이머는 직접 하지 않고
// 명령으로 내보내며, 화면·플랫폼 계층(AudioInput·AudioOutput·LocalQueue)이 실행한다.
// UI·브라우저 API에 의존하지 않는다. 전이 표는 shared/fixtures/transitions.json.

import clientDefaults from '../../../shared/client-defaults.json'

/** 대기·듣기·처리 중·말하기·쉬기·오프라인 보관·정리 */
export type SessionStateName =
  | 'idle'
  | 'listening'
  | 'processing'
  | 'speaking'
  | 'paused'
  | 'offline'
  | 'closing'

export type EndStatus = 'active' | 'paused' | 'ended'

export interface SessionState {
  name: SessionStateName
  turnId: string | null // 지금 답변 턴(끼어들기 cancel 대상)
  lastPlayed: number // 마지막으로 재생을 끝낸 문장 번호(-1: 아직 없음)
  turnFinished: boolean // 이번 턴의 done을 받았다
  playbackIdle: boolean // 받은 문장을 다 재생했다(done이 재생보다 늦게 와도 바로 넘어가게)
  endStatus: EndStatus // done이 알려 준 세션 상태(재생이 끝나면 이 상태로 간다)
  queued: number // 오프라인 큐에 남은 발화 수(이번 대화)
  connected: boolean // 서버에 닿는가(전송 실패면 false, online·성공한 턴이면 true)
  sendingQueued: boolean // 지금 처리 중인 턴이 보관한 말이다(정보용: 전이에는 쓰지 않는다)
  userSpeaking: boolean // 사용자가 말하는 중이다(speech_start 뒤 speech_end 전, 마이크를 끄면 false)
  endConfirmOpen: boolean // 대화종료 확인 창이 열려 있다(규약 6.3)
}

export type SessionEvent =
  | { type: 'tap' }
  | { type: 'long_press' }
  | { type: 'pause' } // 일시 중단 버튼(듣기에서만 받는다)
  // 대화종료 버튼과 확인 창(규약 6.3). 상태는 바꾸지 않고 창만 열고 닫는다
  | { type: 'end_request' }
  | { type: 'end_confirm' }
  | { type: 'end_cancel' }
  // 인사말 턴. 인사말은 SSE가 아니라 시작 응답으로 오므로 플랫폼이 재생을 시작하며 보낸다
  // (재생할 소리가 없으면 바로 playback_idle을 보낸다)
  | { type: 'session_started'; turnId: string }
  | { type: 'start_failed'; code: string }
  | { type: 'speech_start' }
  | { type: 'speech_end'; utteranceId: string }
  | { type: 'turn'; turnId: string }
  // 턴 ID가 지금 턴과 다르면(취소한 턴의 늦은 이벤트) 무시한다
  | { type: 'sentence'; turnId: string; index: number }
  | { type: 'turn_done'; turnId: string; sessionStatus: EndStatus }
  // turnId: turn 이벤트 뒤의 오류면 그 턴 ID, 턴 시작 전 오류(요청 실패 등)면 null
  | { type: 'turn_error'; turnId: string | null; code: string }
  | { type: 'note_saved' }
  | { type: 'sentence_played'; index: number }
  | { type: 'playback_idle' }
  | { type: 'send_failed'; utteranceId: string } // 새 말을 보내다 네트워크 실패
  | { type: 'offline_notice_done' }
  | { type: 'online' }
  | { type: 'queue_sent'; remaining: number } // 큐의 말 하나를 서버가 받았다(remaining: 남은 수)
  | { type: 'queue_send_failed' } // 큐의 말을 보내다 네트워크 실패(말은 큐에 그대로)
  | { type: 'idle_timeout' }
  | { type: 'session_closed' }
  | { type: 'end_failed'; code: string }

export type SessionCommand =
  | { type: 'startSession' }
  | { type: 'sendTurn'; utteranceId: string }
  | { type: 'cancelTurn'; turnId: string; lastPlayed: number }
  | { type: 'endSession' }
  | { type: 'micOn' }
  | { type: 'micOff' }
  | { type: 'setVadMode'; mode: 'normal' | 'playback' } // 재생 중에는 VAD 임계값을 올린다
  | { type: 'stopPlayback' }
  | { type: 'queueUtterance'; utteranceId: string }
  | { type: 'speakOfflineNotice' }
  | { type: 'sendQueued' } // 큐의 가장 오래된 말을 보통 턴으로 보낸다(결과 이벤트는 sendTurn과 같다)
  | { type: 'playSound'; name: 'listen' | 'saved' | 'offline' }
  | { type: 'showEndConfirm' }
  | { type: 'hideEndConfirm' }
  | { type: 'notifyError'; code: string }
  | { type: 'startIdleTimer'; minutes: number }
  | { type: 'clearIdleTimer' }

export interface SessionConfig {
  // 마지막 발화 뒤 이 시간 동안 말이 없으면(쉬는 중 포함) 대화를 끝낸다. 서버 안전망과 같은 값
  idleTimeoutMinutes: number
}

// 프로필을 받기 전 대체값(shared/client-defaults.json). 실제 값은 /api/profile의 client.session이다
export const DEFAULT_SESSION_CONFIG: SessionConfig = {
  idleTimeoutMinutes: clientDefaults.session.idle_timeout_minutes,
}

export interface Transition {
  state: SessionState
  commands: SessionCommand[]
}

export const initialSession: SessionState = {
  name: 'idle',
  turnId: null,
  lastPlayed: -1,
  turnFinished: false,
  playbackIdle: true,
  endStatus: 'active',
  queued: 0,
  connected: true,
  sendingQueued: false,
  userSpeaking: false,
  endConfirmOpen: false,
}

// 세션이 서버에서 이미 끝났다는 오류(규약 2절: 클라이언트는 끝난 상태로 간다)
const SESSION_GONE = new Set(['session_ended', 'session_not_found'])

const NEW_TURN = {
  turnId: null,
  lastPlayed: -1,
  turnFinished: false,
  playbackIdle: true,
  endStatus: 'active',
  sendingQueued: false,
} as const

function enterListening(state: SessionState, config: SessionConfig, commands: SessionCommand[]): Transition {
  return {
    state: { ...state, ...NEW_TURN, name: 'listening' },
    commands: [
      ...commands,
      { type: 'micOn' },
      { type: 'setVadMode', mode: 'normal' },
      { type: 'playSound', name: 'listen' },
      { type: 'startIdleTimer', minutes: config.idleTimeoutMinutes },
    ],
  }
}

function enterPaused(state: SessionState, config: SessionConfig): Transition {
  return {
    state: { ...state, ...NEW_TURN, name: 'paused', userSpeaking: false },
    commands: [{ type: 'micOff' }, { type: 'startIdleTimer', minutes: config.idleTimeoutMinutes }],
  }
}

function enterClosing(state: SessionState, commands: SessionCommand[]): Transition {
  return {
    state: { ...state, ...NEW_TURN, name: 'closing', userSpeaking: false },
    commands: [...commands, { type: 'micOff' }, { type: 'clearIdleTimer' }, { type: 'endSession' }],
  }
}

/** 큐의 가장 오래된 말을 보통 턴으로 보낸다(연결이 돌아오면 제니가 차례로 대답한다, S3-12). */
function sendQueued(state: SessionState, commands: SessionCommand[]): Transition {
  return {
    state: { ...state, ...NEW_TURN, name: 'processing', sendingQueued: true },
    commands: [...commands, { type: 'clearIdleTimer' }, { type: 'sendQueued' }],
  }
}

/** 연결돼 있고 보관한 말이 있으면 그것부터 보내고, 아니면 듣는다. 끼어들기에는 쓰지 않는다
 * (사용자가 말하려는 것이므로 바로 듣는다). */
function listenOrSendQueued(state: SessionState, config: SessionConfig, commands: SessionCommand[]): Transition {
  if (state.connected && state.queued > 0) return sendQueued(state, commands)
  return enterListening(state, config, commands)
}

/** 턴이 끝나고 들려줄 것도 다 들려줬다: done의 세션 상태로 간다(쉬기·끝내기 도구 반영). */
function finishTurn(state: SessionState, config: SessionConfig): Transition {
  if (state.endStatus === 'paused') return enterPaused(state, config)
  if (state.endStatus === 'ended') return enterClosing(state, [])
  return listenOrSendQueued(state, config, [])
}

/** 진행 중인 답변을 멈추는 명령(끼어들기·종료). 들려준 문장까지만 기록하도록 마지막 재생 번호를 보낸다. */
function cancelCurrent(state: SessionState): SessionCommand[] {
  return state.turnId === null ? [] : [{ type: 'cancelTurn', turnId: state.turnId, lastPlayed: state.lastPlayed }]
}

const unchanged = (state: SessionState): Transition => ({ state, commands: [] })

// 마이크가 켜져 있는 상태(듣기에서 켜고 쉬기·정리에서 끈다)
const MIC_ON = new Set<SessionStateName>(['listening', 'processing', 'speaking', 'offline'])

/** 상태에 이벤트를 적용한다. 표에 없는 조합은 상태도 명령도 바꾸지 않는다. */
export function transition(
  state: SessionState,
  event: SessionEvent,
  config: SessionConfig = DEFAULT_SESSION_CONFIG,
): Transition {
  // 대화종료 확인 창(규약 6.3). 대기·정리에서는 버튼이 없으므로 열지 않는다
  switch (event.type) {
    case 'end_request':
      if (state.name === 'idle' || state.name === 'closing' || state.endConfirmOpen) return unchanged(state)
      return { state: { ...state, endConfirmOpen: true }, commands: [{ type: 'showEndConfirm' }] }
    case 'end_cancel':
      if (!state.endConfirmOpen) return unchanged(state)
      return { state: { ...state, endConfirmOpen: false }, commands: [{ type: 'hideEndConfirm' }] }
    case 'end_confirm':
      // 창이 열려 있을 때만 받는다. 길게 누르기와 같은 종료다(창 닫기는 아래에서 앞에 붙는다)
      if (!state.endConfirmOpen) return unchanged(state)
      event = { type: 'long_press' }
      break
  }
  const result = step(state, event, config)
  // 창이 열린 채 정리나 대기로 가면(서버가 끝냄·무발화 종료 등) 창도 닫는다
  if (state.endConfirmOpen && (result.state.name === 'closing' || result.state.name === 'idle')) {
    return {
      state: { ...result.state, endConfirmOpen: false },
      commands: [{ type: 'hideEndConfirm' }, ...result.commands],
    }
  }
  return result
}

function step(state: SessionState, event: SessionEvent, config: SessionConfig): Transition {
  // 마이크가 켜진 상태에서 사용자가 말하는 중인지 적어 둔다(아래 상태별 처리는 바뀐 값을 본다).
  // speech_start는 발화마다 한 번뿐이라, 처리 중에 시작한 말은 답변이 온 뒤에도 기억해야 한다
  if ((event.type === 'speech_start' || event.type === 'speech_end') && MIC_ON.has(state.name)) {
    state = { ...state, userSpeaking: event.type === 'speech_start' }
  }

  // 어느 상태에서나 같은 이벤트
  switch (event.type) {
    case 'online': {
      const online = { ...state, connected: true }
      // 듣는 중이면 보관한 말부터 보낸다(다른 상태는 그 상태가 끝날 때 보낸다)
      if (state.name === 'listening' && state.queued > 0) return sendQueued(online, [])
      return { state: online, commands: [] }
    }
    case 'queue_sent':
      return { state: { ...state, queued: Math.max(event.remaining, 0), connected: true }, commands: [] }
    case 'note_saved':
      return state.name === 'idle' ? unchanged(state) : { state, commands: [{ type: 'playSound', name: 'saved' }] }
    case 'long_press':
      if (state.name === 'idle') return unchanged(state)
      // 끝내기 응답이 오지 않아 정리에서 멈췄을 때의 탈출구(서버 끝내기는 멱등이고 무발화 감시가 정리한다)
      if (state.name === 'closing') return { state: { ...initialSession, queued: state.queued }, commands: [] }
      return enterClosing(state, [
        ...(state.name === 'speaking' || state.name === 'offline' ? [{ type: 'stopPlayback' } as const] : []),
        ...cancelCurrent(state),
      ])
  }

  switch (state.name) {
    case 'idle':
      if (event.type === 'tap') {
        // 큐는 대화마다 따로다(이전 대화의 남은 말은 플랫폼이 기록만 남기기로 보낸다)
        return { state: { ...initialSession, connected: state.connected, name: 'processing' }, commands: [{ type: 'startSession' }] }
      }
      return unchanged(state)

    case 'listening':
      // 일시 중단 버튼: 마이크를 끄고 쉰다(말하던 중이면 그 말은 버린다). 큰 버튼으로 다시 듣는다
      if (event.type === 'pause') return enterPaused(state, config)
      if (event.type === 'speech_end') {
        if (state.queued > 0) {
          // 앞선 발화가 큐에 남아 있으면 순서를 지키려고 이 발화도 큐 뒤에 넣고, 연결돼 있으면
          // 가장 오래된 것부터 보낸다
          const queued = { ...state, queued: state.queued + 1 }
          const enqueue: SessionCommand = { type: 'queueUtterance', utteranceId: event.utteranceId }
          if (state.connected) return sendQueued(queued, [enqueue])
          return {
            state: queued,
            commands: [enqueue, { type: 'startIdleTimer', minutes: config.idleTimeoutMinutes }],
          }
        }
        return {
          state: { ...state, ...NEW_TURN, name: 'processing' },
          commands: [{ type: 'clearIdleTimer' }, { type: 'sendTurn', utteranceId: event.utteranceId }],
        }
      }
      if (event.type === 'idle_timeout') return enterClosing(state, [])
      return unchanged(state)

    case 'processing':
      switch (event.type) {
        case 'session_started':
          // 인사말 재생 시작. 인사말은 이미 끝난 턴이다
          return {
            state: { ...state, ...NEW_TURN, name: 'speaking', turnId: event.turnId, turnFinished: true, playbackIdle: false },
            commands: [{ type: 'setVadMode', mode: 'playback' }],
          }
        case 'start_failed':
          return { state: { ...initialSession, queued: state.queued }, commands: [{ type: 'notifyError', code: event.code }] }
        case 'turn':
          return {
            state: { ...state, ...NEW_TURN, turnId: event.turnId, connected: true, sendingQueued: state.sendingQueued },
            commands: [],
          }
        case 'sentence':
          if (event.turnId !== state.turnId) return unchanged(state)
          if (state.userSpeaking) {
            // 앞말을 보낸 뒤 이어서 말하는 중에 답이 왔다: 반쪽 말에 답하지 않게 끼어들기로 처리하고
            // 이어 하는 말을 마저 듣는다(서버는 들려준 문장이 없다는 안내와 함께 앞말을 맥락에 남긴다)
            return enterListening(state, config, [{ type: 'stopPlayback' }, ...cancelCurrent(state)])
          }
          return {
            state: { ...state, name: 'speaking', playbackIdle: false },
            commands: [{ type: 'setVadMode', mode: 'playback' }],
          }
        case 'turn_done':
          if (event.turnId !== state.turnId) return unchanged(state)
          // 들려줄 문장 없이 끝났다(쉬기·끝내기 도구만 쓴 답 등)
          return finishTurn({ ...state, turnFinished: true, endStatus: event.sessionStatus }, config)
        case 'turn_error':
          if (event.turnId !== null && event.turnId !== state.turnId) return unchanged(state)
          return failTurn(state, event.code, config, [])
        case 'send_failed':
          return {
            state: { ...state, ...NEW_TURN, name: 'offline', queued: state.queued + 1, connected: false },
            commands: [
              { type: 'queueUtterance', utteranceId: event.utteranceId },
              // 안내 음성을 발화로 잡지 않게 재생 중 임계값을 쓴다
              { type: 'setVadMode', mode: 'playback' },
              { type: 'playSound', name: 'offline' },
              { type: 'speakOfflineNotice' },
            ],
          }
        case 'speech_end':
          // 답변을 기다리는 중에 한 말(잠깐 쉬었다 이어 말함, 보관한 말을 보내는 중에 한 말)은 버리지 않고
          // 큐 뒤에 넣는다. 턴이 끝나면 연결돼 있는 한 큐부터 차례로 보낸다(listenOrSendQueued)
          return {
            state: { ...state, queued: state.queued + 1 },
            commands: [{ type: 'queueUtterance', utteranceId: event.utteranceId }],
          }
        case 'queue_send_failed':
          // 보관한 말을 다시 보내지 못했다: 이미 안내했으므로 조용히 다시 듣는다(말은 큐에 그대로)
          return enterListening({ ...state, connected: false }, config, [])
        case 'tap':
          // 답변을 기다리는 중 버튼: 이번 답변을 취소하고 다시 듣는다(턴 시작 전이면 기다린다).
          // 검색 안내 음성(tool.notice)이 나오는 중일 수 있어 재생도 멈춘다
          if (state.turnId === null) return unchanged(state)
          return enterListening(state, config, [{ type: 'stopPlayback' }, ...cancelCurrent(state)])
        default:
          return unchanged(state)
      }

    case 'speaking':
      switch (event.type) {
        case 'sentence_played':
          return { state: { ...state, lastPlayed: Math.max(state.lastPlayed, event.index) }, commands: [] }
        case 'sentence':
          if (event.turnId !== state.turnId) return unchanged(state)
          return { state: { ...state, playbackIdle: false }, commands: [] }
        case 'turn_done': {
          if (event.turnId !== state.turnId) return unchanged(state)
          const done = { ...state, turnFinished: true, endStatus: event.sessionStatus }
          // 문장을 다 들려준 뒤에 done이 왔다(마지막 문장 뒤 도구를 쓴 경우): 더 기다릴 재생이 없다
          return done.playbackIdle ? finishTurn(done, config) : { state: done, commands: [] }
        }
        case 'playback_idle':
          if (state.turnFinished) return finishTurn(state, config)
          return { state: { ...state, playbackIdle: true }, commands: [] } // 다음 문장을 기다린다
        case 'speech_start':
        case 'tap':
          // 끼어들기: 재생을 멈추고 들려준 문장까지만 남기게 한다
          return enterListening(state, config, [{ type: 'stopPlayback' }, ...cancelCurrent(state)])
        case 'speech_end':
          // 말하기 전에 시작한 말이 여기서 끝났다(보통은 끼어들기로 듣기에 있다). 버리지 않고 큐 뒤에 넣어
          // 턴이 끝나면 보낸다
          return {
            state: { ...state, queued: state.queued + 1 },
            commands: [{ type: 'queueUtterance', utteranceId: event.utteranceId }],
          }
        case 'turn_error':
          // 말하는 중에는 이미 턴이 시작됐으므로 턴 시작 전 오류(turnId null)는 늦게 온 것이다
          if (event.turnId !== state.turnId) return unchanged(state)
          return failTurn(state, event.code, config, [{ type: 'stopPlayback' }])
        default:
          return unchanged(state)
      }

    case 'paused':
      if (event.type === 'tap') return listenOrSendQueued(state, config, [])
      if (event.type === 'idle_timeout') return enterClosing(state, [])
      return unchanged(state)

    case 'offline':
      if (event.type === 'offline_notice_done') return listenOrSendQueued(state, config, [])
      if (event.type === 'speech_end') {
        // 안내를 듣는 중에 한 말도 큐에 넣는다
        return {
          state: { ...state, queued: state.queued + 1 },
          commands: [{ type: 'queueUtterance', utteranceId: event.utteranceId }],
        }
      }
      return unchanged(state)

    case 'closing':
      if (event.type === 'session_closed') return { state: { ...initialSession, queued: state.queued }, commands: [] }
      if (event.type === 'end_failed') {
        // 서버 세션은 끝내기가 멱등이고 무발화 감시가 정리한다
        return { state: { ...initialSession, queued: state.queued }, commands: [{ type: 'notifyError', code: event.code }] }
      }
      return unchanged(state)
  }
}

function failTurn(state: SessionState, code: string, config: SessionConfig, commands: SessionCommand[]): Transition {
  if (SESSION_GONE.has(code)) return enterClosing(state, commands)
  return listenOrSendQueued(state, config, [...commands, { type: 'notifyError', code }])
}
