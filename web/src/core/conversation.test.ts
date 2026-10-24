import { describe, expect, it } from 'vitest'
import {
  conversationReducer,
  initialConversation,
  toolNotice,
  type AssistantMessage,
  type ConversationAction,
  type ConversationState,
  type StreamEvent,
  type ToolState,
} from './conversation.ts'

function reduce(actions: ConversationAction[], state = initialConversation): ConversationState {
  return actions.reduce(conversationReducer, state)
}

const started: ConversationAction[] = [
  { type: 'start' },
  {
    type: 'started',
    sessionId: 's1',
    personaName: '도우미',
    greeting: { turnId: 'g1', text: '안녕하세요!' },
  },
]

const ev = (event: StreamEvent): ConversationAction => ({ type: 'event', event })

function tool(phase: 'start' | 'call' | 'end', extra: Partial<StreamEvent> = {}): StreamEvent {
  return {
    type: 'tool',
    phase,
    tool_use_id: 'u1',
    name: 'save_note',
    input: null,
    summary: null,
    is_error: false,
    notice: null,
    ...extra,
  } as StreamEvent
}

function sentence(index: number, text: string): StreamEvent {
  return { type: 'sentence', index, text, audio: null, speech_text: null }
}

function done(turnId: string, text: string, status: 'active' | 'paused' | 'ended' = 'active') {
  return ev({
    type: 'done',
    turn_id: turnId,
    text,
    interrupted: false,
    session_status: status,
    superseded: false,
  })
}

function last(state: ConversationState): AssistantMessage {
  return state.messages.at(-1) as AssistantMessage
}

describe('conversationReducer', () => {
  it('시작하면 인사말 말풍선 하나로 대화를 연다', () => {
    const state = reduce(started)
    expect(state.status).toBe('active')
    expect(state.personaName).toBe('도우미')
    expect(state.messages).toEqual([
      expect.objectContaining({ role: 'assistant', id: 'g1', sentences: ['안녕하세요!'] }),
    ])
  })

  it('턴 이벤트를 받아 문장을 쌓고 done에서 끝낸다', () => {
    const state = reduce([
      ...started,
      { type: 'send', id: 'u-1', text: '안녕' },
      ev({ type: 'turn', turn_id: 'a1' }),
      ev(sentence(0, '첫 문장.')),
      ev(sentence(1, '둘째 문장.')),
      done('a1', '첫 문장. 둘째 문장.'),
    ])
    expect(state.sending).toBe(false)
    expect(state.messages.map((m) => m.role)).toEqual(['assistant', 'user', 'assistant'])
    expect(last(state)).toMatchObject({
      id: 'a1',
      sentences: ['첫 문장.', '둘째 문장.'],
      status: 'done',
    })
  })

  it('unsend는 보내지 못한 내 말풍선만 조용히 뺀다', () => {
    const sent = reduce([...started, { type: 'send', id: 'u-1', text: '못 보냄' }])
    const state = conversationReducer(sent, { type: 'unsend', id: 'u-1' })
    expect(state.messages.map((m) => m.id)).not.toContain('u-1')
    expect(state.error).toBe(sent.error)
  })

  it('send하면 보내는 중이 되고 이전 오류를 지운다', () => {
    const state = reduce([
      ...started,
      { type: 'failed', message: '실패' },
      { type: 'send', id: 'u-1', text: '다시' },
    ])
    expect(state.sending).toBe(true)
    expect(state.error).toBeNull()
  })

  it('도구 이벤트는 tool_use_id로 합치고 입력·요약을 유지한다', () => {
    const state = reduce([
      ...started,
      ev({ type: 'turn', turn_id: 'a1' }),
      ev(tool('start')),
      ev(tool('call', { input: { kind: 'idea', content: '지도 앱' } } as Partial<StreamEvent>)),
      ev(
        tool('end', {
          summary: { kind: 'result', result: '저장 완료(idea): 지도 앱' },
        } as Partial<StreamEvent>),
      ),
    ])
    const [only] = last(state).tools
    expect(last(state).tools).toHaveLength(1)
    expect(only).toMatchObject({ phase: 'end', input: { kind: 'idea', content: '지도 앱' } })
    expect(toolNotice(only)).toBe('아이디어 저장: 지도 앱')
  })

  it('문장 없이 done이 오면 전체 답변으로 채운다', () => {
    const state = reduce([
      ...started,
      ev({ type: 'turn', turn_id: 'a1' }),
      done('a1', '짧은 답', 'paused'),
    ])
    expect(last(state).sentences).toEqual(['짧은 답'])
    expect(state.status).toBe('paused')
  })

  it('error 이벤트는 진행 중인 말풍선을 오류로 표시한다', () => {
    const state = reduce([
      ...started,
      { type: 'send', id: 'u-1', text: '안녕' },
      ev({ type: 'turn', turn_id: 'a1' }),
      ev({ type: 'error', code: 'llm_error', message: '답변을 만들지 못했습니다.' }),
    ])
    expect(state.error).toBe('답변을 만들지 못했습니다.')
    expect(state.sending).toBe(false)
    expect(last(state).status).toBe('error')
  })

  it('시작에 실패하면 처음 화면으로 돌아간다', () => {
    const state = reduce([
      { type: 'start' },
      { type: 'failed', message: '서버에 연결할 수 없어요.' },
    ])
    expect(state.status).toBe('idle')
    expect(state.error).toBe('서버에 연결할 수 없어요.')
  })

  it('모르는 이벤트·액션은 상태를 그대로 둔다', () => {
    const state = reduce(started)
    const unknownEvent = { type: 'event', event: { type: 'transcript', text: '음성' } } as unknown
    expect(conversationReducer(state, unknownEvent as ConversationAction)).toBe(state)
    expect(conversationReducer(state, { type: 'nope' } as unknown as ConversationAction)).toBe(
      state,
    )
  })

  it('서버가 받기 전에 실패한 메시지는 목록에서 뺀다(다시 보내도 중복되지 않게)', () => {
    const state = reduce([
      ...started,
      { type: 'send', id: 'u-1', text: '안녕' },
      {
        type: 'failed',
        message: '이전 답변이 아직 끝나지 않았습니다.',
        code: 'turn_in_progress',
        unsentId: 'u-1',
      },
    ])
    expect(state.messages.map((m) => m.id)).toEqual(['g1'])
    expect(state.status).toBe('active')
  })

  it.each(['session_ended', 'session_not_found'])('%s 오류면 대화를 끝낸다', (code) => {
    const state = reduce([
      ...started,
      { type: 'send', id: 'u-1', text: '안녕' },
      { type: 'failed', message: '끝', code },
    ])
    expect(state.status).toBe('ended')
  })

  it('턴 도중 session_ended 오류 이벤트가 오면 대화를 끝낸다', () => {
    const state = reduce([
      ...started,
      ev({ type: 'turn', turn_id: 'a1' }),
      ev({ type: 'error', code: 'session_ended', message: '대화를 마쳤어요.' }),
    ])
    expect(state.status).toBe('ended')
  })

  it('done의 session_status가 ended면 대화가 끝난다', () => {
    const state = reduce([
      ...started,
      ev({ type: 'turn', turn_id: 'a1' }),
      done('a1', '잘 가요', 'ended'),
    ])
    expect(state.status).toBe('ended')
  })

  it('끝내기 중에는 ending이고, 끝나면 마무리 멘트를 캐릭터 말풍선으로 덧붙인다(한 번만)', () => {
    const ending = reduce([...started, { type: 'ending' }])
    expect(ending.ending).toBe(true)
    const ended = reduce([
      ...started,
      { type: 'ending' },
      { type: 'ended', closing: '오늘 할 일 1개 저장했어요!' },
      { type: 'ended', closing: '오늘 할 일 1개 저장했어요!' },
    ])
    expect(ended.status).toBe('ended')
    expect(ended.ending).toBe(false)
    expect(ended.messages.at(-1)).toMatchObject({
      role: 'assistant',
      sentences: ['오늘 할 일 1개 저장했어요!'],
      status: 'done',
    })
    expect(ended.messages.filter((m) => m.id === 'closing')).toHaveLength(1)
  })

  it('받는 중에 끝내면 그 답변을 받은 데까지 끊긴 답변으로 마무리한다', () => {
    const state = reduce([
      ...started,
      { type: 'send', id: 'u-1', text: '안녕' },
      ev({ type: 'turn', turn_id: 'a1' }),
      ev(sentence(0, '첫 문장.')),
      { type: 'ending' },
    ])
    expect(state.ending).toBe(true)
    expect(last(state)).toEqual(
      expect.objectContaining({
        id: 'a1',
        sentences: ['첫 문장.'],
        status: 'done',
        interrupted: true,
      }),
    )
  })

  it('끝내기가 실패하면 ending을 푼다', () => {
    const state = reduce([...started, { type: 'ending' }, { type: 'failed', message: '연결 안 됨' }])
    expect(state.ending).toBe(false)
  })

  it('새 대화를 시작하면 이전 대화 상태를 모두 지운다', () => {
    const ended = reduce([...started, { type: 'ended', closing: '안녕!' }])
    const fresh = conversationReducer(ended, { type: 'start' })
    expect(fresh).toMatchObject({ status: 'starting', messages: [], sessionId: null, error: null })
  })
})

describe('toolNotice', () => {
  const base: ToolState = {
    id: 'u1',
    name: 'save_note',
    phase: 'start',
    input: null,
    summary: null,
    isError: false,
  }

  it.each<[Partial<ToolState>, string | null]>([
    [{}, '저장 중…'],
    [{ phase: 'call', input: { kind: 'todo', content: '전화' } }, '할 일 저장 중…'],
    [{ phase: 'end', input: { kind: 'idea', content: '지도 앱' } }, '아이디어 저장: 지도 앱'],
    [{ phase: 'end', input: { kind: 'todo', content: '전화하기' } }, '할 일 저장: 전화하기'],
    [{ phase: 'end', input: { kind: 'memo', content: '휴관일' } }, '메모 저장: 휴관일'],
    [{ phase: 'end', input: { kind: 'todo' }, isError: true }, '할 일을 저장하지 못했어요'],
    [{ phase: 'end', isError: true }, '메모를 저장하지 못했어요'],
    [{ phase: 'end', input: { kind: 'toString', content: 'x' } }, '메모 저장: x'],
    [{ name: 'set_nickname' }, '호칭 바꾸는 중…'],
    [{ name: 'set_nickname', phase: 'end', input: { nickname: '길동님' } }, '호칭 변경: 길동님'],
    [{ name: 'set_nickname', phase: 'end' }, '호칭 변경 완료'],
    [
      { name: 'set_nickname', phase: 'end', input: { nickname: '길동님' }, isError: true },
      '호칭을 바꾸지 못했어요',
    ],
    [{ name: 'search_notes' }, '지난 메모 찾는 중…'],
    [
      { name: 'search_notes', phase: 'call', input: { keyword: '쓰레기통' } },
      "지난 메모에서 '쓰레기통' 찾는 중…",
    ],
    [
      { name: 'search_notes', phase: 'end', input: { keyword: '쓰레기통' } },
      '지난 메모 찾기: 쓰레기통',
    ],
    [{ name: 'search_conversations' }, '지난 대화 찾는 중…'],
    [
      { name: 'search_conversations', phase: 'call', input: { keyword: '장터 이름' } },
      "지난 대화에서 '장터 이름' 찾는 중…",
    ],
    [
      { name: 'search_conversations', phase: 'end', input: { keyword: '장터 이름' } },
      '지난 대화 찾기: 장터 이름',
    ],
    [{ name: 'set_model' }, '모델 바꾸는 중…'],
    [{ name: 'set_model', phase: 'end', input: { model: 'opus' } }, '모델 변경: opus'],
    [{ name: 'set_model', phase: 'end', isError: true }, '모델을 바꾸지 못했어요'],
    [{ name: 'summarize_session', phase: 'end' }, '대화 정리 완료'],
    [{ name: 'pause_session' }, null],
    [{ name: 'end_session', phase: 'end' }, null],
    [{ name: 'unknown_tool' }, null],
    // 외부 MCP 도구(M5): 서버 이름 없이 도구 이름만 보인다
    [{ name: 'mcp__maps__search_place' }, 'search_place 사용 중'],
    [{ name: 'mcp__maps__a__b' }, 'a__b 사용 중'],
    [{ name: 'mcp__maps' }, null],
  ])('%o → %s', (patch, expected) => {
    expect(toolNotice({ ...base, ...patch })).toBe(expected)
  })
})
