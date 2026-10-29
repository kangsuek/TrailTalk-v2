import { useCallback, useEffect, useReducer, useRef, useState, type KeyboardEvent } from 'react'
import CountPills from '../components/CountPills.tsx'
import Header from '../components/Header.tsx'
import Markdown from '../components/Markdown.tsx'
import ModeToggle from '../components/ModeToggle.tsx'
import { readMode, rememberMode, type InputMode } from '../hooks/inputMode.ts'
import { monthDayLabel, type JournalStatus, type NoteCounts } from '../core/journal.ts'
import { joinSentences, plainText } from '../core/markdown.ts'
import type { Connection } from '../core/connection.ts'
import {
  ApiError,
  endSession,
  sendTurn,
  startSession,
  type SessionReopened,
} from '../api/conversation.ts'
import { getJournal, listOpenIdeas, type OpenIdea } from '../api/journal.ts'
import {
  conversationReducer,
  initialConversation,
  toolNotice,
  type AssistantMessage,
  type Message,
  type SessionStatus,
} from '../core/conversation.ts'
import type { SessionStateName } from '../core/index.ts'
import { useVoiceConversation } from './useVoiceConversation.ts'
import type { VoiceClosed, VoiceDeps } from './voiceController.ts'
import VoiceDock from './VoiceDock.tsx'

const MAX_LENGTH = 4000

const STATUS_LABEL: Record<SessionStatus, string> = {
  idle: '',
  starting: '시작하는 중…',
  active: '글 대화',
  paused: '쉬는 중',
  ended: '대화 끝남',
}

// 음성 대화 중 헤더 이름 아래 한 줄(상태 머신의 상태)
const VOICE_STATUS_LABEL: Record<SessionStateName, string> = {
  idle: '',
  listening: '듣고 있어요',
  processing: '생각하는 중',
  speaking: '말하는 중',
  paused: '쉬는 중',
  offline: '연결이 끊겼어요',
  closing: '정리 중…',
}

const VOICE_FAILED = '음성 기능을 불러오지 못했어요. 글로 대화해 주세요.'

/** 끝낸 대화의 정리 결과. saved가 null이면 서버가 알려 주지 못했다(그만 기다렸거나 불러오지 못함) */
interface Summary {
  sessionId: string
  epoch: number
  saved: NoteCounts | null
  journalStatus: JournalStatus
}

function Spinner() {
  return (
    <svg className="ic j-spin" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  )
}

function errorMessage(error: unknown): string {
  return error instanceof ApiError ? error.message : '문제가 생겼어요. 다시 해 주세요.'
}

function AssistantBubble({ message }: { message: AssistantMessage }) {
  const notices = message.tools
    .map((tool) => ({ tool, text: toolNotice(tool) }))
    .filter((n) => n.text)
  const waiting = message.status === 'streaming' && message.sentences.length === 0
  return (
    <li className="bubble bubble-assistant" data-status={message.status}>
      {message.sentences.length > 0 && <Markdown text={joinSentences(message.sentences)} />}
      {waiting && <p className="bubble-wait">생각하는 중…</p>}
      {notices.map(({ tool, text }) => (
        <p key={tool.id} className="tool-note" data-error={tool.isError}>
          {text}
        </p>
      ))}
      {message.interrupted && <p className="bubble-sub">여기까지만 전해졌어요</p>}
      {message.status === 'error' && <p className="bubble-sub">답변이 끊겼어요</p>}
    </li>
  )
}

// 내가 말하는 동안 보이는 말풍선(시안 대화 02): 파형과 "말하는 중"
function SpeakingBubble() {
  return (
    <li className="bubble bubble-user bubble-speaking">
      <span className="wave" aria-hidden="true">
        {[10, 20, 28, 16, 24, 12, 6].map((height, i) => (
          <i key={i} style={{ height }} />
        ))}
      </span>
      <span>말하는 중</span>
    </li>
  )
}

function MessageItem({ message }: { message: Message }) {
  if (message.role === 'user') {
    return <li className="bubble bubble-user">{message.text}</li>
  }
  return <AssistantBubble message={message} />
}

export default function ConversationScreen({
  connection = 'checking',
  onSessionChange,
  resume = null,
  onResumed,
  restoreId = null,
  onOpenJournal,
  voiceDeps,
}: {
  connection?: Connection
  /** 진행 중인 대화가 생기거나 끝났을 때(끝나면 null) 알린다 */
  onSessionChange?: (sessionId: string | null) => void
  /** 일지 상세에서 다시 연 대화(재개 인사말까지 포함한 전문). 받으면 이어서 대화한다 */
  resume?: SessionReopened | null
  /** resume을 받아 화면에 올렸다 */
  onResumed?: () => void
  /** 이 기기에서 진행 중이던 대화(새로고침 뒤). 일지 상세의 전문으로 화면을 채우고 이어 간다 */
  restoreId?: string | null
  /** 일지 상세를 연다(시작 화면의 아이디어 카드, 끝난 화면의 "일지에서 보기") */
  onOpenJournal?: (sessionId: string) => void
  /** 음성 대화의 마이크·재생·서버 호출(시험에서 가짜로 바꾼다) */
  voiceDeps?: Partial<VoiceDeps>
}) {
  const [state, dispatch] = useReducer(conversationReducer, initialConversation)
  const [draft, setDraft] = useState('')
  const aborter = useRef<AbortController | null>(null)
  const counter = useRef(0)
  const listRef = useRef<HTMLOListElement>(null)
  const [restoring, setRestoring] = useState(restoreId !== null)
  const [ideas, setIdeas] = useState<OpenIdea[]>([])
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [summary, setSummary] = useState<Summary | null>(null)
  const onSessionChangeRef = useRef(onSessionChange)
  useEffect(() => {
    onSessionChangeRef.current = onSessionChange
  })
  const reported = useRef(false) // 진행 중인 대화를 알린 적이 있다(끝났을 때만 null을 알린다)
  const finalized = useRef<string | null>(null) // 마무리(끝내기 응답)를 이미 받았거나 받는 대화
  // 대화를 다시 열 때마다 올린다(그 전 끝내기의 요약을 보이지 않게). 렌더는 상태, 비동기 쓰기는 ref를 본다
  const epoch = useRef(0)
  const [epochShown, bumpEpoch] = useReducer((n: number) => n + 1, 0)
  const [mode, setMode] = useState<InputMode>(readMode) // 시작할 방식(기기에 기억한다)
  // 음성 대화 중 보이는 조작 영역(음성/글). 대화마다 음성에서 시작하므로 어느 대화에서 골랐는지 함께 둔다
  const [panelChoice, setPanelChoice] = useState<{ sessionId: string | null; panel: InputMode }>({
    sessionId: null,
    panel: 'voice',
  })
  // 음성 대화가 끝내기 응답을 받았다: 컨트롤러가 이미 마무리했으므로 화면이 다시 부르지 않는다.
  // finalized를 여기서 동기로 먼저 세워 두어야 아래 마무리 효과가 같은 대화를 다시 끝내지 않는다(순서 의존)
  const handleClosed = useCallback((sessionId: string, closed: VoiceClosed) => {
    finalized.current = sessionId
    setSummary({ sessionId, epoch: epoch.current, saved: closed.saved, journalStatus: closed.journalStatus })
  }, [])
  const voice = useVoiceConversation(dispatch, handleClosed, state.personaName, voiceDeps)
  const voiceActive = voice.machine.name !== 'idle' // 음성 대화(인사말 재생부터 정리까지)
  const voiceFailed = voice.ready === false // 음성 모듈을 불러오지 못했다
  const startMode: InputMode = mode === 'voice' && !voiceFailed ? 'voice' : 'text'
  const panel: InputMode = panelChoice.sessionId === state.sessionId ? panelChoice.panel : 'voice'

  const openSessionId =
    state.status === 'active' || state.status === 'paused' ? state.sessionId : null
  useEffect(() => {
    if (openSessionId) {
      reported.current = true
      onSessionChange?.(openSessionId)
    } else if (reported.current) {
      reported.current = false
      onSessionChange?.(null)
    }
  }, [openSessionId, onSessionChange])

  // 새로고침 뒤 복원: 같은 기기에서 기억한 진행 중 대화는 reopen 없이 상세의 전문으로 화면을 채우고
  // 같은 세션에 턴을 이어 보낸다(규약 2.11). 이미 끝났거나 없으면 기억을 지우고 시작 화면이다.
  // 서버에 닿지 못한 경우는 기억을 남겨 둔다(다음 새로고침에 다시 시도)
  useEffect(() => {
    if (!restoreId) return
    const controller = new AbortController()
    void (async () => {
      try {
        const detail = await getJournal(restoreId, controller.signal)
        if (controller.signal.aborted) return
        if (detail.session.status === 'ended') onSessionChangeRef.current?.(null)
        else {
          dispatch({
            type: 'resumed',
            sessionId: restoreId,
            personaName: detail.persona_name,
            turns: detail.turns,
            status: detail.session.status,
          })
        }
      } catch (error) {
        if (controller.signal.aborted) return
        if (error instanceof ApiError && error.status === 404) onSessionChangeRef.current?.(null)
      } finally {
        if (!controller.signal.aborted) setRestoring(false)
      }
    })()
    return () => controller.abort()
  }, [restoreId])

  // 시작 화면이 보일 때마다 "지난 아이디어 이어 가기" 목록을 다시 불러온다(없거나 못 불러오면 숨긴다)
  useEffect(() => {
    if (state.status !== 'idle' || restoring) return
    const controller = new AbortController()
    listOpenIdeas(5, controller.signal)
      .then(setIdeas)
      .catch(() => {
        if (!controller.signal.aborted) setIdeas([])
      })
    return () => controller.abort()
  }, [state.status, restoring])

  // 끝내기 도구·서버의 무발화 종료로 끝난 대화는 끝내기 API를 불러 마무리 멘트와 저장 개수를 받는다
  // (규약 2.9). 끝내기 버튼으로 끝낸 대화는 그 응답으로 이미 마무리했다
  useEffect(() => {
    const sessionId = state.sessionId
    if (state.status !== 'ended' || !sessionId || state.ending) return
    if (finalized.current === sessionId || voiceActive) return // 음성 대화는 컨트롤러가 마무리한다
    finalized.current = sessionId
    const controller = new AbortController()
    void (async () => {
      try {
        const closed = await endSession(sessionId, controller.signal)
        dispatch({ type: 'ended', closing: closed.closing })
        setSummary({
          sessionId,
          epoch: epoch.current,
          saved: closed.saved,
          journalStatus: closed.journal_status,
        })
      } catch {
        if (!controller.signal.aborted) {
          setSummary({ sessionId, epoch: epoch.current, saved: null, journalStatus: null })
        }
      }
    })()
    return () => controller.abort()
  }, [state.status, state.sessionId, state.ending, voiceActive])

  const voiceResume = voice.resume
  useEffect(() => {
    if (!resume) return
    aborter.current?.abort()
    // 다시 연 대화는 새로 끝나므로 앞서 끝낸 기록(마무리 호출·요약)을 잊는다
    finalized.current = null
    epoch.current += 1
    bumpEpoch()
    // 음성으로 다시 연 대화는 컨트롤러가 재개 인사말을 들려주며 이어 간다
    if (resume.session.mode === 'voice' && voiceResume(resume)) {
      onResumed?.()
      return
    }
    dispatch({
      type: 'resumed',
      sessionId: resume.session.id,
      personaName: resume.persona.name,
      turns: resume.turns,
    })
    onResumed?.()
  }, [resume, onResumed, voiceResume])

  // 화면이 사라지면 진행 중인 요청을 끊는다(서버가 턴을 멈춘다)
  useEffect(() => () => aborter.current?.abort(), [])

  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [state.messages, voice.machine.userSpeaking])

  async function start() {
    aborter.current?.abort()
    const controller = (aborter.current = new AbortController())
    dispatch({ type: 'start' })
    setDraft('')
    try {
      const started = await startSession('text', controller.signal)
      dispatch({
        type: 'started',
        sessionId: started.session.id,
        personaName: started.persona.name,
        greeting: {
          turnId: started.greeting.turn_id,
          text: started.greeting.text,
        },
      })
    } catch (error) {
      if (controller.signal.aborted) return
      dispatch({ type: 'failed', message: errorMessage(error) })
    }
  }

  // 보내는 동안 새로 쓰던 글이 있으면 덮어쓰지 않는다
  function restoreDraft(text: string) {
    setDraft((current) => (current.trim() ? current : text))
  }

  async function send() {
    const text = draft.trim()
    if (!text || state.sending || !state.sessionId || state.status === 'ended') return
    if (voiceActive) {
      // 음성 대화 중 글: 듣는 중에만 받는다(컨트롤러가 말풍선과 전송을 맡는다)
      if (voice.sendText(text, restoreDraft)) setDraft('')
      return
    }
    const id = `u-${(counter.current += 1)}`
    const controller = (aborter.current = new AbortController())
    let gotTurn = false // turn 이벤트 전의 오류는 서버가 메시지를 받지 못한 것이다(규약 2.10)
    dispatch({ type: 'send', id, text })
    setDraft('')
    try {
      await sendTurn(
        state.sessionId,
        text,
        (event) => {
          if (event.type === 'turn') gotTurn = true
          if (event.type === 'error' && !gotTurn) {
            // 서버가 받지 못한 메시지: 말풍선을 빼고 입력창으로 되돌린다. 세션이 끝났다면 되돌리지 않는다
            dispatch({
              type: 'failed',
              message: event.message,
              code: event.code,
              unsentId: id,
            })
            if (event.code !== 'session_ended' && event.code !== 'session_not_found') restoreDraft(text)
            return
          }
          dispatch({ type: 'event', event })
        },
        controller.signal,
      )
    } catch (error) {
      if (controller.signal.aborted) return
      const code = error instanceof ApiError ? error.code : undefined
      const unsent = !gotTurn // 스트림이 열리기 전(JSON 오류)·turn 전에 끊김
      dispatch({
        type: 'failed',
        message: errorMessage(error),
        code,
        unsentId: unsent ? id : undefined,
      })
      if (unsent && code !== 'session_ended' && code !== 'session_not_found') restoreDraft(text)
    }
  }

  async function end() {
    const sessionId = state.sessionId
    if (!sessionId || state.ending) return
    setConfirmEnd(false)
    finalized.current = sessionId // 이 요청의 응답으로 마무리한다
    aborter.current?.abort() // 받는 중인 답변은 받은 데까지 끊는다
    const controller = (aborter.current = new AbortController())
    setDraft('') // 끝낸 대화를 다시 열어도 쓰던 글이 남아 있지 않게
    dispatch({ type: 'ending' })
    try {
      const closed = await endSession(sessionId, controller.signal)
      dispatch({ type: 'ended', closing: closed.closing })
      setSummary({
        sessionId,
        epoch: epoch.current,
        saved: closed.saved,
        journalStatus: closed.journal_status,
      })
    } catch (error) {
      if (controller.signal.aborted) return
      finalized.current = null
      dispatch({ type: 'failed', message: errorMessage(error) })
    }
  }

  // 정리를 기다리다 그만둔다. 대화는 서버에서 이미 끝났고 정리는 서버가 계속한다
  function stopWaiting() {
    const sessionId = state.sessionId
    if (!sessionId || !state.ending) return
    aborter.current?.abort()
    if (voiceActive) voice.longPress() // 컨트롤러가 요청을 끊고 대기로 간다("그만 기다리기")
    dispatch({ type: 'ended' })
    setSummary({ sessionId, epoch: epoch.current, saved: null, journalStatus: 'pending' })
  }

  // 시작 화면의 방식 선택. 고른 방식은 기기에 기억한다
  function changeMode(next: InputMode) {
    setMode(next)
    rememberMode(next)
  }

  // 음성 대화 중의 조작 영역 전환(대화는 그대로 이어진다)
  function changePanel(next: InputMode) {
    setPanelChoice({ sessionId: state.sessionId, panel: next })
  }

  function startVoice() {
    setDraft('')
    voice.tap()
  }

  function cancelEndConfirm() {
    if (voice.machine.endConfirmOpen) voice.cancelEnd()
    setConfirmEnd(false)
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // 한글 조합 중의 Enter(글자 확정)는 보내지 않는다
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    void send()
  }

  if (restoring) {
    return (
      <section className="chat chat-start" aria-label="대화 불러오는 중">
        <Header initial="T" name="TrailTalk" sub="대화 불러오는 중" heading connection={connection} />
        <div className="chat-start-body">
          <p className="chat-start-sub" role="status">
            하던 대화를 불러오고 있어요…
          </p>
        </div>
      </section>
    )
  }

  if (state.status === 'idle' || state.status === 'starting') {
    return (
      <section className="chat chat-start" aria-label="대화 시작">
        <Header initial="T" name="TrailTalk" sub="대화 전" heading connection={connection} />
        <div className="chat-start-body">
          {startMode === 'voice' ? (
            <>
              <h2 className="chat-start-title">걸으면서 이야기해요</h2>
              <p className="chat-start-sub">
                버튼을 한 번 누르면 이어폰으로 대화가 시작돼요. 그 뒤로는 화면을 만지지 않아도 돼요.
              </p>
            </>
          ) : (
            <>
              <h2 className="chat-start-title">글로 이야기해 볼까요?</h2>
              <p className="chat-start-sub">버튼을 누르면 대화가 시작돼요.</p>
            </>
          )}
          {voiceFailed && mode === 'voice' && (
            <p className="chat-error" role="status">
              {VOICE_FAILED}
            </p>
          )}
          {state.error && (
            <p className="chat-error" role="alert">
              {state.error}
            </p>
          )}
          {ideas.length > 0 && (
            <section className="ideas" aria-label="지난 아이디어 이어 가기">
              <h2 className="sh">지난 아이디어 이어 가기</h2>
              {ideas.map((idea) => (
                <button
                  key={idea.id}
                  type="button"
                  className="idea-card"
                  onClick={() => onOpenJournal?.(idea.session_id)}
                >
                  <span className="j-meta">{monthDayLabel(idea.created_at)}</span>
                  <span className="idea-text">{plainText(idea.content)}</span>
                  <CountPills counts={idea.counts} />
                </button>
              ))}
            </section>
          )}
        </div>
        {startMode === 'voice' ? (
          <VoiceDock state={state.status === 'starting' ? 'starting' : 'idle'} onTap={startVoice}>
            <ModeToggle mode={startMode} onChange={changeMode} voiceDisabled={voice.ready !== true} disabled={state.status === 'starting'} />
          </VoiceDock>
        ) : (
          <div className="dock">
            <ModeToggle mode={startMode} onChange={changeMode} voiceDisabled={voice.ready !== true} disabled={state.status === 'starting'} />
            <button
              type="button"
              className="btn btn-primary btn-big"
              disabled={state.status === 'starting'}
              onClick={() => void start()}
            >
              {state.status === 'starting' ? '시작하는 중…' : '글로 대화 시작'}
            </button>
          </div>
        )}
      </section>
    )
  }

  const ended = state.status === 'ended'
  const sum =
    summary?.sessionId === state.sessionId && summary.epoch === epochShown ? summary : null
  const initial = state.personaName?.slice(0, 1) ?? ''
  return (
    <section className="chat" aria-label="대화">
      <Header
        initial={initial}
        name={state.personaName ?? ''}
        sub={
          state.ending
            ? '정리 중…'
            : voiceActive
              ? VOICE_STATUS_LABEL[voice.machine.name]
              : STATUS_LABEL[state.status]
        }
        tone={voiceActive && !state.ending ? voice.machine.name : undefined}
        heading
        connection={connection}
      />
      <ol className="msgs" ref={listRef} aria-label="대화 내용" aria-live="polite">
        {state.messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
        {voiceActive && voice.machine.userSpeaking && <SpeakingBubble />}
      </ol>
      {state.error && (
        <p className="chat-error" role="alert">
          {state.error}
        </p>
      )}
      {ended ? (
        <div className="composer composer-ended">
          <section className="closing-card" aria-label="오늘의 정리">
            {sum?.saved && (
              <>
                <div className="sh">오늘 저장한 것</div>
                <CountPills counts={sum.saved} all />
              </>
            )}
            {(sum === null || sum.journalStatus === 'pending') && (
              <p className="closing-row">
                <Spinner />
                <span>
                  <strong>일지를 정리하고 있어요</strong>
                  <span className="closing-sub">끝나면 일지에서 볼 수 있어요.</span>
                </span>
              </p>
            )}
            {sum?.journalStatus === 'failed' && (
              <p className="closing-sub">
                일지를 정리하지 못했어요. 일지에서 다시 정리할 수 있어요.
              </p>
            )}
            {state.sessionId && (
              <button
                type="button"
                className="btn"
                onClick={() => onOpenJournal?.(state.sessionId!)}
              >
                일지에서 보기
              </button>
            )}
          </section>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => (startMode === 'voice' ? startVoice() : void start())}
          >
            새 대화 시작
          </button>
        </div>
      ) : state.ending ? (
        <div className="composer composer-ended">
          <section className="closing-card" role="status" aria-label="정리 중">
            <p className="closing-row">
              <Spinner />
              <span>
                <strong>일지를 정리하고 있어요</strong>
                <span className="closing-sub">요약과 할 일을 모으는 중이에요. 최대 45초.</span>
              </span>
            </p>
            <div className="bar-track bar-track-primary" aria-hidden="true">
              <i />
            </div>
          </section>
          <button type="button" className="link-btn" onClick={stopWaiting}>
            그만 기다리기
          </button>
        </div>
      ) : voiceActive && panel === 'voice' ? (
        <VoiceDock
          state={voice.machine.name}
          onTap={voice.tap}
          onLongPress={voice.longPress}
          onEnd={voice.requestEnd}
        >
          <ModeToggle mode={panel} onChange={changePanel} />
        </VoiceDock>
      ) : (
        <div className="composer">
          {voiceActive && <ModeToggle mode={panel} onChange={changePanel} />}
          <div className="composer-row">
            <textarea
              aria-label="메시지"
              rows={2}
              maxLength={MAX_LENGTH}
              value={draft}
              placeholder="메시지를 입력하세요"
              disabled={state.ending}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={onKeyDown}
            />
            <button
              type="button"
              className="send"
              aria-label="보내기"
              disabled={
                !draft.trim() ||
                state.sending ||
                (voiceActive && (voice.machine.name !== 'listening' || voice.machine.queued > 0))
              }
              onClick={() => void send()}
            >
              <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 12l16-8-6 16-3-7z" />
              </svg>
            </button>
          </div>
          <div className="composer-actions">
            <button
              type="button"
              className="btn btn-ghost"
              disabled={state.ending}
              onClick={() => (voiceActive ? voice.requestEnd() : setConfirmEnd(true))}
            >
              <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              대화종료
            </button>
          </div>
        </div>
      )}
      {(confirmEnd || voice.machine.endConfirmOpen) && (
        <div
          className="dialog-back dialog-back-float"
          onKeyDown={(event) => event.key === 'Escape' && cancelEndConfirm()}
        >
          <div
            className="dialog dialog-float"
            role="alertdialog"
            aria-modal="true"
            aria-label="대화 종료 확인"
            aria-describedby="end-desc"
          >
            <h2>대화를 끝낼까요?</h2>
            <p id="end-desc">
              지금까지 이야기한 내용을 일지로 정리해요. 끝낸 대화는 일지에서 다시 이어서 할 수 있어요.
            </p>
            <div className="dialog-stack">
              <button
                type="button"
                className="btn btn-primary"
                onClick={() => (voiceActive ? voice.confirmEnd() : void end())}
              >
                끝내고 정리하기
              </button>
              <button type="button" className="btn" autoFocus onClick={cancelEndConfirm}>
                계속 대화하기
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
