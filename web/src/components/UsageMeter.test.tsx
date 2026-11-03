import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { UsageContext, type UsageState } from '../hooks/useUsage.ts'
import UsageMeter from './UsageMeter.tsx'

const soon = (hours: number) => new Date(Date.now() + hours * 3_600_000).toISOString()

function renderMeter(state: Omit<UsageState, 'now'>) {
  render(
    <UsageContext.Provider value={{ ...state, now: new Date() }}>
      <UsageMeter />
    </UsageContext.Provider>,
  )
  return screen.getByRole('meter', { name: 'Claude 남은 토큰' })
}

describe('UsageMeter', () => {
  afterEach(cleanup)

  it('덜 남은 한도의 남은 %와 초기화 시각을 보인다', () => {
    const meter = renderMeter({
      limits: {
        status: 'allowed',
        five_hour: { utilization: 0.38, resets_at: soon(3.5) },
        seven_day: { utilization: 0.1, resets_at: soon(50) },
      },
      unavailable: false,
    })
    expect(meter).toHaveTextContent('남은 토큰 62%')
    expect(meter).toHaveTextContent('3시간 뒤 초기화')
    expect(meter).toHaveAttribute('aria-valuenow', '62')
  })

  it('첫 답변 전(값 없음)에는 막대를 비우고 안내한다', () => {
    const meter = renderMeter({ limits: null, unavailable: false })
    expect(meter).toHaveTextContent('대화하면 표시')
    expect(meter).not.toHaveAttribute('aria-valuenow')
  })

  it('오프라인이면 마지막 값이 있어도 확인 불가로 보인다', () => {
    const meter = renderMeter({
      limits: {
        status: 'allowed',
        five_hour: { utilization: 0.1, resets_at: soon(2) },
        seven_day: null,
      },
      unavailable: true,
    })
    expect(meter).toHaveTextContent('확인 불가')
    expect(meter).not.toHaveTextContent('90%')
  })
})
