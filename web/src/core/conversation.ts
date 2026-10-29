// 글 대화 화면 상태(리듀서)와 도구 알림 문구.
// 서버 SSE 이벤트(docs/client-contract.md 2.4)를 말풍선 목록으로 바꾼다. 문장 분할·요약은 서버가 하고
// 여기서는 받은 그대로 쌓기만 한다. UI·브라우저 API에 의존하지 않는다.

import { groupTurns, type Turn } from './journal.ts'

// 서버 SSE 이벤트(app/api/events.py, 규약 2.4). core는 api 폴더를 가져오지 않으므로 필요한 모양을
// 여기에 적고, 생성 타입(schema.d.ts)과 같은지는 api/conversation.ts가 타입으로 확인한다.
/** 음성 턴에서만 `turn` 바로 앞에 오는 첫 이벤트: 인식한 글(M3). */
export interface TranscriptEvent {
  type: 'transcript'
  text: string
}

export interface TurnEvent {
  type: 'turn'
  turn_id: string
}

export interface SentenceEvent {
  type: 'sentence'
  index: number
  text: string
  audio: string | null
  speech_text: string | null
}

/** 도구 결과 요약(종류 kind로 구분. M1은 앱 도구의 result뿐이다. 규약 2.6) */
export interface ToolSummary {
  kind: 'result'
  result?: unknown
}

export interface ToolEvent {
  type: 'tool'
  phase: 'start' | 'call' | 'end'
  tool_use_id: string
  name: string
  input: Record<string, unknown> | null
  summary: ToolSummary | null
  is_error: boolean
  notice: { text: string; audio: string | null } | null
}

export interface DoneEvent {
  type: 'done'
  turn_id: string
  text: string
  interrupted: boolean
  session_status: 'active' | 'paused' | 'ended'
  superseded: boolean
}

export interface ErrorEvent {
  type: 'error'
  code: string
  message: string
}

export type StreamEvent =
  | TranscriptEvent
  | TurnEvent
  | SentenceEvent
  | ToolEvent
  | DoneEvent
  | ErrorEvent

export interface ToolState {
  id: string
  name: string
  phase: ToolEvent['phase']
  input: Record<string, unknown> | null
  summary: ToolSummary | null
  isError: boolean
}

export interface UserMessage {
  role: 'user'
  id: string
  text: string
}

export interface AssistantMessage {
  role: 'assistant'
  id: string
  sentences: string[]
  tools: ToolState[]
  status: 'streaming' | 'done' | 'error'
  interrupted: boolean
}

export type Message = UserMessage | AssistantMessage

export type SessionStatus = 'idle' | 'starting' | 'active' | 'paused' | 'ended'

export interface ConversationState {
  status: SessionStatus
  sessionId: string | null
  personaName: string | null
  messages: Message[]
  sending: boolean
  // 끝내기 요청 중
  ending: boolean
  error: string | null
}

export type ConversationAction =
  | { type: 'start' }
  // 서버에 있는 대화를 그대로 이어 간다(다시 열기 응답, 같은 기기의 새로고침 복원). turns는 전문이다
  | {
      type: 'resumed'
      sessionId: string
      personaName: string
      turns: Turn[]
      // 서버에 있는 상태(쉬는 중이면 paused). 없으면 active
      status?: 'active' | 'paused'
    }
  | {
      type: 'started'
      sessionId: string
      personaName: string
      greeting: { turnId: string; text: string }
    }
  | { type: 'send'; id: string; text: string }
  | { type: 'event'; event: StreamEvent }
  // code: 서버 오류 코드(세션이 이미 끝났으면 대화를 끝낸다), unsentId: 서버가 받기 전에 실패해
  // 입력창으로 되돌린 사용자 메시지(목록에서 뺀다)
  | { type: 'failed'; message: string; code?: string; unsentId?: string }
  // 서버가 받기 전에 대화가 끝나 보내지 못한 사용자 메시지를 조용히 뺀다(오류 문구 없음)
  | { type: 'unsend'; id: string }
  | { type: 'ending' }
  // closing: 서버가 준 마무리 멘트(캐릭터 말풍선으로 보인다)
  | { type: 'ended'; closing?: string }

const SESSION_GONE = new Set(['session_ended', 'session_not_found'])

export const initialConversation: ConversationState = {
  status: 'idle',
  sessionId: null,
  personaName: null,
  messages: [],
  sending: false,
  ending: false,
  error: null,
}

/** 진행 중인 답변 말풍선을 바꾼다(없으면 그대로). */
function updateStreaming(
  messages: Message[],
  update: (message: AssistantMessage) => AssistantMessage,
): Message[] {
  const index = messages.findLastIndex((m) => m.role === 'assistant' && m.status === 'streaming')
  if (index === -1) return messages
  const next = messages.slice()
  next[index] = update(messages[index] as AssistantMessage)
  return next
}

function applyTool(tools: ToolState[], event: ToolEvent): ToolState[] {
  const index = tools.findIndex((t) => t.id === event.tool_use_id)
  const previous = index === -1 ? null : tools[index]
  const tool: ToolState = {
    id: event.tool_use_id,
    name: event.name,
    phase: event.phase,
    input: event.input ?? previous?.input ?? null,
    summary: event.summary ?? previous?.summary ?? null,
    isError: event.is_error,
  }
  if (index === -1) return [...tools, tool]
  const next = tools.slice()
  next[index] = tool
  return next
}

function applyEvent(state: ConversationState, event: StreamEvent): ConversationState {
  switch (event.type) {
    case 'transcript':
      return state // 내 말풍선은 음성 연결(voiceController)이 인식 결과로 만든다(M3-13)
    case 'turn':
      return {
        ...state,
        messages: [
          ...state.messages,
          {
            role: 'assistant',
            id: event.turn_id,
            sentences: [],
            tools: [],
            status: 'streaming',
            interrupted: false,
          },
        ],
      }
    case 'sentence':
      return {
        ...state,
        messages: updateStreaming(state.messages, (m) => ({
          ...m,
          sentences: [...m.sentences, event.text],
        })),
      }
    case 'tool':
      return {
        ...state,
        messages: updateStreaming(state.messages, (m) => ({
          ...m,
          tools: applyTool(m.tools, event),
        })),
      }
    case 'done':
      return {
        ...state,
        sending: false,
        status: event.session_status,
        messages: updateStreaming(state.messages, (m) => ({
          ...m,
          // 문장 이벤트를 하나도 못 받았으면 전체 답변으로 채운다
          sentences: m.sentences.length > 0 || !event.text ? m.sentences : [event.text],
          status: 'done',
          interrupted: event.interrupted,
        })),
      }
    case 'error':
      return {
        ...state,
        // 턴 도중 세션이 끝났으면(끝내기 요청 뒤 오류 등) 끝난 화면으로 간다
        status: SESSION_GONE.has(event.code) ? 'ended' : state.status,
        sending: false,
        error: event.message,
        messages: updateStreaming(state.messages, (m) => ({ ...m, status: 'error' })),
      }
    default:
      return state // 서버가 먼저 추가한 새 이벤트는 무시한다(앱이 멈추지 않게)
  }
}

export function conversationReducer(
  state: ConversationState,
  action: ConversationAction,
): ConversationState {
  switch (action.type) {
    case 'start':
      return { ...initialConversation, status: 'starting' }
    case 'resumed':
      return {
        ...initialConversation,
        status: action.status ?? 'active',
        sessionId: action.sessionId,
        personaName: action.personaName,
        messages: messagesFromTurns(action.turns),
      }
    case 'started':
      return {
        ...state,
        status: 'active',
        sessionId: action.sessionId,
        personaName: action.personaName,
        error: null,
        messages: [
          {
            role: 'assistant',
            id: action.greeting.turnId,
            sentences: [action.greeting.text],
            tools: [],
            status: 'done',
            interrupted: false,
          },
        ],
      }
    case 'send':
      return {
        ...state,
        sending: true,
        error: null,
        messages: [...state.messages, { role: 'user', id: action.id, text: action.text }],
      }
    case 'event':
      return applyEvent(state, action.event)
    case 'unsend':
      return { ...state, messages: state.messages.filter((m) => m.id !== action.id) }
    case 'failed': {
      const messages = action.unsentId
        ? state.messages.filter((m) => m.id !== action.unsentId)
        : state.messages
      return {
        ...state,
        ending: false,
        // 시작 실패면 처음 화면으로, 서버에서 이미 끝난 세션이면 끝난 화면으로 간다
        status:
          state.status === 'starting'
            ? 'idle'
            : action.code && SESSION_GONE.has(action.code)
              ? 'ended'
              : state.status,
        sending: false,
        error: action.message,
        messages: updateStreaming(messages, (m) => ({ ...m, status: 'error' })),
      }
    }
    case 'ending':
      // 받는 중에 끝내면 그 답변은 받은 데까지 끊긴 답변으로 마무리한다(대기 표시가 남지 않게)
      return {
        ...state,
        sending: true,
        ending: true,
        error: null,
        messages: updateStreaming(state.messages, (m) => ({
          ...m,
          status: 'done',
          interrupted: true,
        })),
      }
    case 'ended': {
      const closing: AssistantMessage[] = action.closing
        ? [
            {
              role: 'assistant',
              id: 'closing',
              sentences: [action.closing],
              tools: [],
              status: 'done',
              interrupted: false,
            },
          ]
        : []
      return {
        ...state,
        status: 'ended',
        sending: false,
        ending: false,
        messages: [...state.messages.filter((m) => m.id !== 'closing'), ...closing],
      }
    }
    default:
      return state
  }
}

/**
 * 저장된 전문을 말풍선으로. 병합된 뒷말은 앞말과 한 말풍선이다(내 말은 줄을 바꿔 잇고, 답변은 한
 * 문단으로 잇는다). 끝까지 말하지 못한 답변은 interrupted로 남는다.
 */
export function messagesFromTurns(turns: readonly Turn[]): Message[] {
  return groupTurns(turns).map((bubble): Message => {
    if (bubble.role === 'user') {
      return { role: 'user', id: bubble.id, text: bubble.texts.join('\n') }
    }
    return {
      role: 'assistant',
      id: bubble.id,
      sentences: [bubble.texts.join(' ')],
      tools: [],
      status: 'done',
      interrupted: bubble.interrupted,
    }
  })
}

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}

// 저장한 노트 종류의 이름과 목적격(을/를)
const NOTE_LABELS: Record<string, [string, string]> = {
  idea: ['아이디어', '아이디어를'],
  todo: ['할 일', '할 일을'],
  memo: ['메모', '메모를'],
}

const EXTERNAL_PREFIX = 'mcp__'

/** 도구 상태를 한 줄 알림으로. 보여 줄 필요가 없는 도구(쉬기·끝내기)는 null. */
export function toolNotice(tool: ToolState): string | null {
  const finished = tool.phase === 'end'
  switch (tool.name) {
    case 'save_note': {
      // 도구 입력의 종류(idea·todo·memo)대로 부른다. start 단계에는 입력이 없어 종류를 모른다
      const kind = String(tool.input?.kind)
      const [label, object] = Object.hasOwn(NOTE_LABELS, kind)
        ? NOTE_LABELS[kind]
        : NOTE_LABELS.memo
      if (!finished) return tool.input ? `${label} 저장 중…` : '저장 중…'
      if (tool.isError) return `${object} 저장하지 못했어요`
      const content = text(tool.input?.content)
      return content ? `${label} 저장: ${content}` : `${label} 저장 완료`
    }
    case 'search_notes': {
      const keyword = text(tool.input?.keyword)
      if (!finished) return keyword ? `지난 메모에서 '${keyword}' 찾는 중…` : '지난 메모 찾는 중…'
      return keyword ? `지난 메모 찾기: ${keyword}` : '지난 메모 찾기 완료'
    }
    case 'search_conversations': {
      const keyword = text(tool.input?.keyword)
      if (!finished) return keyword ? `지난 대화에서 '${keyword}' 찾는 중…` : '지난 대화 찾는 중…'
      return keyword ? `지난 대화 찾기: ${keyword}` : '지난 대화 찾기 완료'
    }
    case 'summarize_session':
      return finished ? '대화 정리 완료' : '대화 정리 중…'
    case 'set_model': {
      if (!finished) return '모델 바꾸는 중…'
      if (tool.isError) return '모델을 바꾸지 못했어요'
      const model = text(tool.input?.model)
      return model ? `모델 변경: ${model}` : '모델 변경 완료'
    }
    case 'set_nickname': {
      if (!finished) return '호칭 바꾸는 중…'
      if (tool.isError) return '호칭을 바꾸지 못했어요'
      const nickname = text(tool.input?.nickname)
      return nickname ? `호칭 변경: ${nickname}` : '호칭 변경 완료'
    }
    default: {
      // 외부 MCP 도구(M5)는 mcp__<서버>__<도구>로 온다. 서버 이름은 보이지 않는다(규약 2.5)
      if (tool.name.startsWith(EXTERNAL_PREFIX)) {
        const name = tool.name.slice(EXTERNAL_PREFIX.length).split('__').slice(1).join('__')
        return name ? `${name} 사용 중` : null
      }
      return null
    }
  }
}
