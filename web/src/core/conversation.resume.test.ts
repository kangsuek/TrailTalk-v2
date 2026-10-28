import { describe, expect, it } from 'vitest'
import { conversationReducer, initialConversation, messagesFromTurns } from './conversation.ts'
import type { Turn } from './journal.ts'

function turn(id: string, seq: number, role: Turn['role'], text: string, extra: Partial<Turn> = {}): Turn {
  return {
    id,
    seq,
    role,
    text,
    interrupted: false,
    merged_from: null,
    created_at: 'x',
    attachments: [],
    ...extra,
  }
}

describe('messagesFromTurns', () => {
  it('전문을 말풍선으로 바꾸고 병합된 뒷말은 한 말풍선으로 잇는다', () => {
    const messages = messagesFromTurns([
      turn('t0', 0, 'assistant', '안녕하세요'),
      turn('t1', 1, 'user', '앞말'),
      turn('t2', 2, 'user', '뒷말', { merged_from: 't1' }),
      turn('t3', 3, 'assistant', '답이에요', { interrupted: true }),
    ])
    expect(messages).toEqual([
      {
        role: 'assistant',
        id: 't0',
        sentences: ['안녕하세요'],
        tools: [],
        status: 'done',
        interrupted: false,
      },
      { role: 'user', id: 't1', text: '앞말\n뒷말' },
      { role: 'assistant', id: 't3', sentences: ['답이에요'], tools: [], status: 'done', interrupted: true },
    ])
  })
})

describe('resumed', () => {
  it('서버에 있는 대화를 이어 가는 상태로 바꾼다', () => {
    const state = conversationReducer(
      { ...initialConversation, status: 'ended', error: '이전 오류', sending: true },
      {
        type: 'resumed',
        sessionId: 's1',
        personaName: '제니',
        turns: [turn('t0', 0, 'assistant', '다시 왔어요')],
      },
    )
    expect(state).toMatchObject({
      status: 'active',
      sessionId: 's1',
      personaName: '제니',
      error: null,
      sending: false,
      ending: false,
    })
    expect(state.messages).toHaveLength(1)
  })
})
