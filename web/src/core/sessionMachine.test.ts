import { describe, expect, it } from 'vitest'
import clientDefaults from '../../../shared/client-defaults.json'
import fixture from '../../../shared/fixtures/transitions.json'
import {
  DEFAULT_SESSION_CONFIG,
  initialSession,
  transition,
  type SessionConfig,
  type SessionEvent,
  type SessionState,
  type SessionStateName,
} from './sessionMachine'

// 전이 표(shared/fixtures/transitions.json)는 상태 전이의 기준이다
interface Step {
  event: SessionEvent
  expect: { state: SessionStateName; commands: unknown[]; context?: Partial<SessionState> }
}

const config = fixture.config as SessionConfig
const cases = fixture.cases as unknown as { name: string; steps: Step[] }[]

describe('세션 상태 머신 전이 표', () => {
  it('표의 상태 이름이 머신의 상태와 같다', () => {
    expect(Object.keys(fixture.states).sort()).toEqual(
      ['closing', 'idle', 'listening', 'offline', 'paused', 'processing', 'speaking'].sort(),
    )
  })

  it.each(cases.map((c) => [c.name, c] as const))('%s', (_, testCase) => {
    let state = initialSession
    testCase.steps.forEach((step, i) => {
      const result = transition(state, step.event, config)
      const where = `${i + 1}단계 ${step.event.type}`
      expect(result.state.name, where).toBe(step.expect.state)
      expect(result.commands, where).toEqual(step.expect.commands)
      if (step.expect.context) expect(result.state, where).toMatchObject(step.expect.context)
      state = result.state
    })
  })
})

describe('세션 상태 머신 성질', () => {
  const states = Object.keys(fixture.states) as SessionStateName[]
  const events: SessionEvent[] = [
    { type: 'tap' },
    { type: 'long_press' },
    { type: 'session_started', turnId: 't' },
    { type: 'start_failed', code: 'x' },
    { type: 'speech_start' },
    { type: 'speech_end', utteranceId: 'u' },
    { type: 'turn', turnId: 't' },
    { type: 'sentence', turnId: 't', index: 0 },
    { type: 'turn_done', turnId: 't', sessionStatus: 'active' },
    { type: 'turn_error', turnId: null, code: 'x' },
    { type: 'note_saved' },
    { type: 'sentence_played', index: 0 },
    { type: 'playback_idle' },
    { type: 'send_failed', utteranceId: 'u' },
    { type: 'offline_notice_done' },
    { type: 'online' },
    { type: 'queue_sent', remaining: 0 },
    { type: 'queue_send_failed' },
    { type: 'idle_timeout' },
    { type: 'session_closed' },
    { type: 'end_failed', code: 'x' },
    { type: 'end_request' },
    { type: 'end_confirm' },
    { type: 'end_cancel' },
  ]

  it('모든 상태와 이벤트 조합에서 예외 없이 알려진 상태로 간다', () => {
    for (const name of states) {
      for (const event of events) {
        const result = transition({ ...initialSession, name, turnId: 't' }, event)
        expect(states).toContain(result.state.name)
      }
    }
  })

  it('알 수 없는 이벤트는 상태도 명령도 바꾸지 않는다(서버·플랫폼이 먼저 새 이벤트를 보내도 멈추지 않게)', () => {
    for (const name of states) {
      const state = { ...initialSession, name }
      const result = transition(state, { type: 'future_event' } as unknown as SessionEvent)
      expect(result).toEqual({ state, commands: [] })
    }
  })

  it('입력 상태를 바꾸지 않는다(순수 함수)', () => {
    const state = Object.freeze({ ...initialSession, name: 'speaking' as const, turnId: 't' })
    expect(() => transition(state, { type: 'tap' })).not.toThrow()
    expect(state.name).toBe('speaking')
  })
})

describe('기본 설정', () => {
  it('프로필을 받기 전 대체값은 shared/client-defaults.json에서 온다', () => {
    expect(DEFAULT_SESSION_CONFIG.idleTimeoutMinutes).toBe(clientDefaults.session.idle_timeout_minutes)
  })
})
