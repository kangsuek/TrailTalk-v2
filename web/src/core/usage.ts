// Claude 남은 토큰 표시(계획서 S3-36). UI·브라우저 API에 의존하지 않는다.
// 서버(GET /api/usage)는 구독 한도별 사용률(0~1)과 초기화 시각만 준다. 화면은 두 한도 중
// 덜 남은 쪽(같으면 5시간)을 "남은 %"와 "N시간 뒤 초기화"로 보인다.

export interface UsageWindow {
  utilization: number // 0~1(쓴 비율)
  resets_at: string | null
}

export interface UsageLimits {
  status: string | null // allowed·allowed_warning·rejected
  five_hour: UsageWindow | null
  seven_day: UsageWindow | null
}

export type UsageLevel = 'unknown' | 'ok' | 'low' | 'out'

export interface UsageView {
  window: 'five_hour' | 'seven_day' | null
  remaining: number | null // 남은 %(0~100 정수), 값이 없으면 null
  reset: string | null // 예: "3시간 뒤 초기화"
  level: UsageLevel
}

const LOW_REMAINING = 20 // 이 % 이하면 경고 색

const MINUTE = 60_000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

/** 초기화까지 남은 시간 문구. 지났으면 null */
export function resetLabel(resetsAt: Date, now: Date): string | null {
  const ms = resetsAt.getTime() - now.getTime()
  if (!Number.isFinite(ms) || ms <= 0) return null
  if (ms < MINUTE) return '곧 초기화'
  if (ms < HOUR) return `${Math.floor(ms / MINUTE)}분 뒤 초기화`
  if (ms < DAY) return `${Math.floor(ms / HOUR)}시간 뒤 초기화`
  return `${Math.floor(ms / DAY)}일 뒤 초기화`
}

/** 한도 하나의 남은 %와 초기화 문구. 초기화 시각이 지났으면 새 구간이라 100%로 본다 */
function windowView(
  window: UsageWindow,
  now: Date,
): { remaining: number; reset: string | null; expired: boolean } {
  const resetsAt = window.resets_at === null ? null : new Date(window.resets_at)
  if (
    resetsAt !== null &&
    !Number.isNaN(resetsAt.getTime()) &&
    resetsAt.getTime() <= now.getTime()
  ) {
    return { remaining: 100, reset: null, expired: true }
  }
  const used = Math.min(Math.max(window.utilization, 0), 1)
  return {
    remaining: Math.round((1 - used) * 100),
    reset: resetsAt === null || Number.isNaN(resetsAt.getTime()) ? null : resetLabel(resetsAt, now),
    expired: false,
  }
}

export function usageView(limits: UsageLimits | null, now: Date): UsageView {
  const candidates = (['five_hour', 'seven_day'] as const)
    .map((name) => {
      const window = limits?.[name]
      return window ? { name, ...windowView(window, now) } : null
    })
    .filter((c) => c !== null)
  if (candidates.length === 0)
    return { window: null, remaining: null, reset: null, level: 'unknown' }
  // 덜 남은 쪽(같으면 앞의 5시간)
  const pick = candidates.reduce((a, b) => (b.remaining < a.remaining ? b : a))
  // 서버의 status는 다음 답변 때 바뀌므로, 고른 한도가 이미 초기화됐으면 rejected를 믿지 않는다
  const out = pick.remaining <= 0 || (limits?.status === 'rejected' && !pick.expired)
  const level: UsageLevel = out ? 'out' : pick.remaining <= LOW_REMAINING ? 'low' : 'ok'
  return {
    window: pick.name,
    remaining: pick.remaining,
    reset: pick.reset,
    level,
  }
}
