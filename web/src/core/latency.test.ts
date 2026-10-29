import { describe, expect, it } from 'vitest'
import { createLatencyTracker } from './latency'

function clock(start = 1000) {
  let t = start
  return { now: () => t, set: (value: number) => (t = value) }
}

describe('지연 보고 계산', () => {
  it('말 끝 → 요청 시작, 요청 시작 → 첫 답변 소리를 한 번만 만든다', () => {
    const c = clock(10_000)
    const tracker = createLatencyTracker(c.now)
    tracker.begin(8_150) // 말이 8150에 끝났고 지금(10000)이 요청 시작
    tracker.attach('t1')
    c.set(15_400)
    expect(tracker.playbackStarted(false)).toEqual({
      turnId: 't1',
      speechToRequestMs: 1850,
      requestToPlaybackMs: 5400,
      firstSoundNotice: false,
    })
    expect(tracker.playbackStarted(false)).toBeNull() // 턴마다 한 번
  })

  it('검색 안내 음성이 첫 소리면 표시한다', () => {
    const c = clock()
    const tracker = createLatencyTracker(c.now)
    tracker.begin(null)
    tracker.attach('t1')
    c.set(5000)
    expect(tracker.playbackStarted(true)?.firstSoundNotice).toBe(true)
  })

  it('말 끝 시각을 모르면 요청 시각으로 보고 음수는 0으로 맞춘다', () => {
    const c = clock(2000)
    const tracker = createLatencyTracker(c.now)
    tracker.begin(null)
    tracker.attach('t1')
    expect(tracker.playbackStarted(false)?.speechToRequestMs).toBe(0)
    tracker.begin(3000) // 말이 끝난 시각이 요청보다 늦을 수는 없지만 계산이 음수가 되지 않게
    tracker.attach('t2')
    expect(tracker.playbackStarted(false)?.speechToRequestMs).toBe(0)
  })

  it('턴 ID를 받기 전의 소리(맞장구 등)는 보고하지 않고 기다린다', () => {
    const c = clock()
    const tracker = createLatencyTracker(c.now)
    tracker.begin(0)
    expect(tracker.playbackStarted(false)).toBeNull()
    tracker.attach('t1')
    expect(tracker.playbackStarted(false)).not.toBeNull()
  })

  it('끊은 턴과 시작하지 않은 턴은 보고하지 않는다', () => {
    const c = clock()
    const tracker = createLatencyTracker(c.now)
    expect(tracker.playbackStarted(false)).toBeNull() // begin 전(인사말·마무리 멘트)
    tracker.begin(0)
    tracker.attach('t1')
    tracker.cancel()
    expect(tracker.playbackStarted(false)).toBeNull()
    tracker.attach('t2') // 취소 뒤의 늦은 이벤트
    expect(tracker.playbackStarted(false)).toBeNull()
  })

  it('다음 턴은 새로 잰다', () => {
    const c = clock(0)
    const tracker = createLatencyTracker(c.now)
    tracker.begin(0)
    tracker.attach('t1')
    c.set(100)
    tracker.playbackStarted(false)
    c.set(1000)
    tracker.begin(900)
    tracker.attach('t2')
    c.set(1600)
    expect(tracker.playbackStarted(false)).toMatchObject({
      turnId: 't2',
      speechToRequestMs: 100,
      requestToPlaybackMs: 600,
    })
  })
})
