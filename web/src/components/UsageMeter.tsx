import { usageView } from '../core/usage.ts'
import { useUsageState } from '../hooks/useUsage.ts'

const WINDOW_NAMES = { five_hour: '5시간', seven_day: '7일' } as const

// 헤더 오른쪽의 "남은 토큰" 막대(시안 대화 01·08·09·11). 첫 답변 전에는 값이 없어 막대를 비우고,
// 서버에 닿지 않으면 "확인 불가"로 보인다. 계산은 core/usage.ts다.
export default function UsageMeter() {
  const { limits, unavailable, now } = useUsageState()
  const view = usageView(limits, now)
  const known = view.remaining !== null && !unavailable
  const head = unavailable ? '남은 토큰' : known ? `남은 토큰 ${view.remaining}%` : '남은 토큰'
  const foot = unavailable ? '확인 불가' : known ? (view.reset ?? '') : '대화하면 표시'
  const valueText = unavailable
    ? '남은 토큰 확인 불가'
    : known
      ? `${WINDOW_NAMES[view.window!]} 한도 ${view.remaining}% 남음${view.reset ? `, ${view.reset}` : ''}`
      : '대화하면 표시'
  return (
    <div
      className="usage"
      data-level={unavailable ? 'unknown' : view.level}
      role="meter"
      aria-label="Claude 남은 토큰"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={known ? view.remaining! : undefined}
      aria-valuetext={valueText}
    >
      <div className="usage-head">{head}</div>
      <div className="usage-bar" aria-hidden="true">
        <i style={{ width: `${known ? view.remaining : 0}%` }} />
      </div>
      <div className="usage-foot">{foot}</div>
    </div>
  )
}
