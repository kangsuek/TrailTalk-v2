import { useEffect, useRef } from 'react'
import { PENDING_POLL_MAX_MS, PENDING_POLL_MS } from '../core/journal.ts'

/**
 * 정리 중(pending)인 동안 3초마다 refresh를 부른다(최대 약 2분, client-contract 3.2). pending이
 * 꺼졌다 다시 켜지면(다시 정리) 시간을 새로 센다. 2분이 지나도 끝나지 않으면 멈춘다.
 */
export function usePendingPoll(pending: boolean, refresh: () => void): void {
  const latest = useRef(refresh)
  useEffect(() => {
    latest.current = refresh
  })
  useEffect(() => {
    if (!pending) return
    const startedAt = Date.now()
    const timer = window.setInterval(() => {
      if (Date.now() - startedAt > PENDING_POLL_MAX_MS) window.clearInterval(timer)
      else latest.current()
    }, PENDING_POLL_MS)
    return () => window.clearInterval(timer)
  }, [pending])
}
