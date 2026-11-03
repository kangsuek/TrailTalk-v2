import { createContext, useContext, useEffect, useState } from 'react'
import { fetchUsage } from '../api/usage.ts'
import { HEALTH_INTERVAL_MS, type Connection } from '../core/connection.ts'
import type { UsageLimits } from '../core/usage.ts'

/** 헤더 막대에 넘기는 값. limits가 null이면 아직 값이 없는 것(첫 답변 전)이다. */
export interface UsageState {
  limits: UsageLimits | null
  /** 서버에 닿지 않아 값을 확인할 수 없다 */
  unavailable: boolean
  /** 값을 불러온 시각. 초기화까지 남은 시간 계산의 기준이다(렌더에서 시계를 읽지 않는다) */
  now: Date
}

export const UsageContext = createContext<UsageState>({
  limits: null,
  unavailable: false,
  now: new Date(),
})

export const useUsageState = (): UsageState => useContext(UsageContext)

/**
 * Claude 남은 토큰(규약 1.3). 서버 연결 확인과 같은 30초마다, 화면이 다시 보일 때 불러온다.
 * 오프라인이면 마지막 값을 버리지 않고 "확인 불가"로만 보인다.
 */
export function useUsage(connection: Connection): UsageState {
  const [limits, setLimits] = useState<UsageLimits | null>(null)
  const [failed, setFailed] = useState(false)
  const [now, setNow] = useState(() => new Date())
  const online = connection === 'connected'
  useEffect(() => {
    if (!online) return
    const controller = new AbortController()
    let inFlight = false
    const load = () => {
      if (inFlight || document.visibilityState === 'hidden') return
      inFlight = true
      void fetchUsage(controller.signal)
        .then((value) => {
          if (controller.signal.aborted) return
          setLimits(value)
          setFailed(false)
          setNow(new Date())
        })
        .catch(() => {
          if (!controller.signal.aborted) setFailed(true)
        })
        .finally(() => {
          inFlight = false
        })
    }
    load()
    const timer = window.setInterval(load, HEALTH_INTERVAL_MS)
    document.addEventListener('visibilitychange', load)
    return () => {
      controller.abort()
      window.clearInterval(timer)
      document.removeEventListener('visibilitychange', load)
    }
  }, [online])
  return { limits, unavailable: connection === 'offline' || failed, now }
}
