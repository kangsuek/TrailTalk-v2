import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { HEALTH_INTERVAL_MS, type Connection } from '../core/connection.ts'
import { useUsage } from './useUsage.ts'

const body = (used: number) => ({
  status: 'allowed',
  five_hour: { utilization: used, resets_at: '2099-01-01T00:00:00Z' },
  seven_day: null,
  updated_at: '2026-11-02T00:00:00Z',
})

function mockUsage(...used: (number | 'fail')[]) {
  const queue = [...used]
  const fetchMock = vi.fn(async () => {
    const next = queue.length > 1 ? queue.shift()! : queue[0]!
    if (next === 'fail') throw new TypeError('network')
    return new Response(JSON.stringify(body(next)), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('useUsage', () => {
  beforeEach(() => vi.useFakeTimers({ shouldAdvanceTime: true }))
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('연결되면 불러오고 30초마다 다시 불러온다', async () => {
    const fetchMock = mockUsage(0.2, 0.5)
    const { result } = renderHook(() => useUsage('connected'))
    await vi.waitFor(() => expect(result.current.limits?.five_hour?.utilization).toBe(0.2))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEALTH_INTERVAL_MS)
    })
    await vi.waitFor(() => expect(result.current.limits?.five_hour?.utilization).toBe(0.5))
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('연결 전에는 부르지 않고, 오프라인이면 확인 불가이며 마지막 값은 남긴다', async () => {
    const fetchMock = mockUsage(0.2)
    const { result, rerender } = renderHook(({ c }: { c: Connection }) => useUsage(c), {
      initialProps: { c: 'checking' as Connection },
    })
    expect(fetchMock).not.toHaveBeenCalled()
    rerender({ c: 'connected' })
    await vi.waitFor(() => expect(result.current.limits).not.toBeNull())
    rerender({ c: 'offline' })
    expect(result.current.unavailable).toBe(true)
    expect(result.current.limits?.five_hour?.utilization).toBe(0.2)
  })

  it('불러오기가 실패하면 확인 불가이고 다음에 성공하면 돌아온다', async () => {
    mockUsage('fail', 0.3)
    const { result } = renderHook(() => useUsage('connected'))
    await vi.waitFor(() => expect(result.current.unavailable).toBe(true))
    await act(async () => {
      await vi.advanceTimersByTimeAsync(HEALTH_INTERVAL_MS)
    })
    await vi.waitFor(() => expect(result.current.unavailable).toBe(false))
    expect(result.current.limits?.five_hour?.utilization).toBe(0.3)
  })
})
