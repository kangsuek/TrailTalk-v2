import { describe, expect, it } from 'vitest'
import { resetLabel, usageView, type UsageLimits } from './usage.ts'

const NOW = new Date('2026-10-18T12:00:00Z')
const at = (ms: number) => new Date(NOW.getTime() + ms).toISOString()
const HOUR = 3_600_000

function limits(fiveUsed: number | null, weekUsed: number | null, status = 'allowed'): UsageLimits {
  return {
    status,
    five_hour: fiveUsed === null ? null : { utilization: fiveUsed, resets_at: at(3.5 * HOUR) },
    seven_day: weekUsed === null ? null : { utilization: weekUsed, resets_at: at(50 * HOUR) },
  }
}

describe('usage', () => {
  it('초기화까지 남은 시간을 분·시간·일로 적는다', () => {
    expect(resetLabel(new Date(at(30_000)), NOW)).toBe('곧 초기화')
    expect(resetLabel(new Date(at(25 * 60_000)), NOW)).toBe('25분 뒤 초기화')
    expect(resetLabel(new Date(at(3.5 * HOUR)), NOW)).toBe('3시간 뒤 초기화')
    expect(resetLabel(new Date(at(50 * HOUR)), NOW)).toBe('2일 뒤 초기화')
    expect(resetLabel(new Date(at(-1)), NOW)).toBeNull()
  })

  it('값이 없으면 unknown', () => {
    expect(usageView(null, NOW)).toEqual({
      window: null,
      remaining: null,
      reset: null,
      level: 'unknown',
    })
    expect(usageView(limits(null, null), NOW).level).toBe('unknown')
  })

  it('두 한도 중 덜 남은 쪽을 보인다(같으면 5시간)', () => {
    expect(usageView(limits(0.38, 0.07), NOW)).toEqual({
      window: 'five_hour',
      remaining: 62,
      reset: '3시간 뒤 초기화',
      level: 'ok',
    })
    expect(usageView(limits(0.1, 0.85), NOW)).toMatchObject({
      window: 'seven_day',
      remaining: 15,
      reset: '2일 뒤 초기화',
      level: 'low',
    })
    expect(usageView(limits(0.5, 0.5), NOW).window).toBe('five_hour')
    expect(usageView(limits(null, 0.2), NOW).window).toBe('seven_day')
  })

  it('다 썼거나 막혔으면 out, 초기화 시각이 지난 한도는 100%', () => {
    expect(usageView(limits(1, 0.1), NOW).level).toBe('out')
    expect(usageView(limits(0.5, 0.1, 'rejected'), NOW).level).toBe('out')
    const past: UsageLimits = {
      status: 'allowed',
      five_hour: { utilization: 0.9, resets_at: at(-HOUR) },
      seven_day: null,
    }
    expect(usageView(past, NOW)).toMatchObject({
      remaining: 100,
      reset: null,
      level: 'ok',
    })
    // 한도에 걸린 뒤 초기화가 지났으면(다음 답변 전이라 status는 그대로) 막힘으로 보이지 않는다
    expect(usageView({ ...past, status: 'rejected' }, NOW).level).toBe('ok')
    const noReset: UsageLimits = {
      status: null,
      five_hour: { utilization: 0.25, resets_at: null },
      seven_day: null,
    }
    expect(usageView(noReset, NOW)).toMatchObject({
      remaining: 75,
      reset: null,
    })
  })
})
