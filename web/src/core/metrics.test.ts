import { describe, expect, it } from 'vitest'
import { createMetrics } from './metrics'

describe('createMetrics', () => {
  it('프레임과 표식을 시각과 함께 모은다', () => {
    let t = 100
    const metrics = createMetrics(() => t)
    metrics.frame(0.2)
    t = 132
    metrics.frame(0.9)
    t = 140
    metrics.mark('vad_confirm', { mode: 'playback' })
    metrics.mark('source_stop')
    expect(metrics.frames).toEqual([
      { t: 100, p: 0.2 },
      { t: 132, p: 0.9 },
    ])
    expect(metrics.marks).toEqual([
      { t: 140, type: 'vad_confirm', data: { mode: 'playback' } },
      { t: 140, type: 'source_stop' },
    ])
  })

  it('상한을 넘으면 오래된 것부터 버린다', () => {
    let t = 0
    const metrics = createMetrics(() => t++, 3, 2)
    for (let i = 0; i < 5; i++) metrics.frame(i / 10)
    for (let i = 0; i < 4; i++) metrics.mark(`m${i}`)
    expect(metrics.frames.map((f) => f.p)).toEqual([0.2, 0.3, 0.4])
    expect(metrics.marks.map((m) => m.type)).toEqual(['m2', 'm3'])
  })

  it('clear는 같은 배열 객체를 비운다', () => {
    const metrics = createMetrics(() => 1)
    const { frames, marks } = metrics
    metrics.frame(0.5)
    metrics.mark('x')
    metrics.clear()
    expect(frames).toHaveLength(0)
    expect(marks).toHaveLength(0)
    expect(metrics.frames).toBe(frames)
  })
})
