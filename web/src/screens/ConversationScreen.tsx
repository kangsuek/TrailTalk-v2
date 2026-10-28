import { useEffect, useReducer, useRef, useState, type KeyboardEvent } from 'react'
import Header from '../components/Header.tsx'
import Markdown from '../components/Markdown.tsx'
import { joinSentences } from '../core/markdown.ts'
import type { Connection } from '../core/connection.ts'
import {
  ApiError,
  endSession,
  sendTurn,
  startSession,
  type SessionReopened,
} from '../api/conversation.ts'
import {
  conversationReducer,
  initialConversation,
  toolNotice,
  type AssistantMessage,
  type Message,
  type SessionStatus,
} from '../core/conversation.ts'

const MAX_LENGTH = 4000

const STATUS_LABEL: Record<SessionStatus, string> = {
  idle: '',
  starting: '시작하는 중…',
  active: '글 대화',
  paused: '쉬는 중',
  ended: '대화 끝남',
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
}: {
  connection?: Connection
  /** 진행 중인 대화가 생기거나 끝났을 때(끝나면 null) 알린다 */
  onSessionChange?: (sessionId: string | null) => void
  /** 일지 상세에서 다시 연 대화(재개 인사말까지 포함한 전문). 받으면 이어서 대화한다 */
  resume?: SessionReopened | null
  /** resume을 받아 화면에 올렸다 */
  onResumed?: () => void
}) {
  const [state, dispatch] = useReducer(conversationReducer, initialConversation)
  const [draft, setDraft] = useState('')
  const aborter = useRef<AbortController | null>(null)
  const counter = useRef(0)
  const listRef = useRef<HTMLOListElement>(null)

  const openSessionId =
    state.status === 'active' || state.status === 'paused' ? state.sessionId : null
  useEffect(() => {
    onSessionChange?.(openSessionId)
  }, [openSessionId, onSessionChange])

  useEffect(() => {
    if (!resume) return
    aborter.current?.abort()
    dispatch({
      type: 'resumed',
      sessionId: resume.session.id,
      personaName: resume.persona.name,
      turns: resume.turns,
    })
    onResumed?.()
  }, [resume, onResumed])

  // 화면이 사라지면 진행 중인 요청을 끊는다(서버가 턴을 멈춘다)
  useEffect(() => () => aborter.current?.abort(), [])

  useEffect(() => {
    const list = listRef.current
    if (list) list.scrollTop = list.scrollHeight
  }, [state.messages])

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
    if (!state.sessionId || state.ending) return
    aborter.current?.abort() // 받는 중인 답변은 받은 데까지 끊는다
    const controller = (aborter.current = new AbortController())
    setDraft('') // 끝낸 대화를 다시 열어도 쓰던 글이 남아 있지 않게
    dispatch({ type: 'ending' })
    try {
      const closed = await endSession(state.sessionId, controller.signal)
      dispatch({ type: 'ended', closing: closed.closing })
    } catch (error) {
      if (controller.signal.aborted) return
      dispatch({ type: 'failed', message: errorMessage(error) })
    }
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    // 한글 조합 중의 Enter(글자 확정)는 보내지 않는다
    if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    void send()
  }

  if (state.status === 'idle' || state.status === 'starting') {
    return (
      <section className="chat chat-start" aria-label="대화 시작">
        <Header initial="T" name="TrailTalk" sub="대화 전" heading connection={connection} />
        <div className="chat-start-body">
          <h2 className="chat-start-title">글로 이야기해 볼까요?</h2>
          <p className="chat-start-sub">버튼을 누르면 대화가 시작돼요.</p>
          {state.error && (
            <p className="chat-error" role="alert">
              {state.error}
            </p>
          )}
        </div>
        <div className="dock">
          <button
            type="button"
            className="btn btn-primary btn-big"
            disabled={state.status === 'starting'}
            onClick={() => void start()}
          >
            {state.status === 'starting' ? '시작하는 중…' : '글로 대화 시작'}
          </button>
        </div>
      </section>
    )
  }

  const ended = state.status === 'ended'
  const initial = state.personaName?.slice(0, 1) ?? ''
  return (
    <section className="chat" aria-label="대화">
      <Header
        initial={initial}
        name={state.personaName ?? ''}
        sub={state.ending ? '정리 중…' : STATUS_LABEL[state.status]}
        heading
        connection={connection}
      />
      <ol className="msgs" ref={listRef} aria-label="대화 내용" aria-live="polite">
        {state.messages.map((message) => (
          <MessageItem key={message.id} message={message} />
        ))}
      </ol>
      {state.error && (
        <p className="chat-error" role="alert">
          {state.error}
        </p>
      )}
      {ended ? (
        <div className="composer composer-ended">
          <button type="button" className="btn btn-primary" onClick={() => void start()}>
            새 대화 시작
          </button>
        </div>
      ) : (
        <div className="composer">
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
              disabled={!draft.trim() || state.sending}
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
              onClick={() => void end()}
            >
              <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" width="16" height="16">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
              대화종료
            </button>
          </div>
        </div>
      )}
    </section>
  )
}
