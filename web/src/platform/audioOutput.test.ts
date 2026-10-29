import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AudioOutputEvent } from '../core/audio'
import { createAudioOutput } from './audioOutput'

// jsdom에는 Web Audio가 없어 흉내 낸다. 디코드는 바로(또는 지정한 만큼 늦게) 끝나고,
// 재생은 테스트가 finish()를 부를 때 끝난다. 실제처럼 stop()은 끝 알림(onended)을 바로 보내지 않는다
interface FakeSource {
  buffer: { id: string; duration: number } | null
  onended: (() => void) | null
  connect: () => void
  disconnect: () => void
  start: () => void
  stop: () => void
}
const audio = {
  sources: [] as FakeSource[],
  decodeDelay: new Map<string, Promise<void>>(),
  broken: new Set<string>(),
  state: 'running' as 'running' | 'suspended',
  resume: vi.fn(async () => {}),
  startError: false,
}

beforeEach(() => {
  audio.sources = []
  audio.decodeDelay.clear()
  audio.broken.clear()
  audio.state = 'running'
  audio.resume = vi.fn(async () => {})
  audio.startError = false
  vi.stubGlobal(
    'AudioContext',
    class {
      destination = {}
      get state() {
        return audio.state
      }
      resume = () => audio.resume()
      close = vi.fn(async () => {})
      async decodeAudioData(data: ArrayBuffer) {
        const id = new TextDecoder().decode(data)
        await audio.decodeDelay.get(id)
        if (audio.broken.has(id)) throw new Error('decode')
        return { id, duration: 0.5 }
      }
      createBufferSource() {
        const source: FakeSource = {
          buffer: null,
          onended: null,
          connect: () => {},
          disconnect: () => {},
          start: () => {
            if (audio.startError) throw new Error('start')
          },
          stop: () => {},
        }
        audio.sources.push(source)
        return source
      }
    },
  )
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

const b64 = (id: string) => btoa(id)
const tick = () => new Promise((r) => setTimeout(r, 0))

/** 지금 재생 중인 소리의 id */
function nowPlaying() {
  return audio.sources.at(-1)?.buffer?.id
}

async function finish() {
  audio.sources.at(-1)?.onended?.()
  await tick()
}

function deferred() {
  let resolve = () => {}
  const promise = new Promise<void>((r) => (resolve = r))
  return { promise, resolve }
}

function setup(onEvent?: (e: AudioOutputEvent) => void) {
  const events: AudioOutputEvent[] = [] // 머신에 가는 이벤트(재생 시작 알림은 started에 따로)
  const started: (number | null)[] = []
  const output = createAudioOutput((e) => {
    if (e.type === 'started') started.push(e.index)
    else events.push(e)
    onEvent?.(e)
  })
  return { output, events, started }
}

describe('createAudioOutput', () => {
  it('넣은 순서대로 하나씩 재생하고, 문장마다 sentence_played, 다 비면 playback_idle', async () => {
    const { output, events } = setup()
    output.enqueue({ audio: b64('greet'), index: null })
    output.enqueue({ audio: b64('s0'), index: 0 })
    output.enqueue({ audio: b64('s1'), index: 1 })
    await tick()
    expect(nowPlaying()).toBe('greet')
    await finish()
    expect(nowPlaying()).toBe('s0')
    expect(events).toEqual([]) // 인사말(index null)은 문장 이벤트가 없다
    await finish()
    expect(events).toEqual([{ type: 'sentence_played', index: 0 }])
    await finish()
    expect(events).toEqual([
      { type: 'sentence_played', index: 0 },
      { type: 'sentence_played', index: 1 },
      { type: 'playback_idle' },
    ])
  })

  it('소리마다 재생을 시작하면 started로 알린다(지연 측정용)', async () => {
    const { output, started } = setup()
    output.enqueue({ audio: b64('notice'), index: null })
    output.enqueue({ audio: null, index: 0 }) // 소리 없는 문장은 재생하지 않는다
    output.enqueue({ audio: b64('s1'), index: 1 })
    await tick()
    expect(started).toEqual([null])
    await finish()
    expect(started).toEqual([null, 1])
  })

  it('뒤 문장 디코드가 먼저 끝나도 순서를 지킨다', async () => {
    const gate = deferred()
    audio.decodeDelay.set('s0', gate.promise)
    const { output } = setup()
    output.enqueue({ audio: b64('s0'), index: 0 })
    output.enqueue({ audio: b64('s1'), index: 1 })
    await tick()
    expect(audio.sources).toHaveLength(0)
    gate.resolve()
    await tick()
    expect(nowPlaying()).toBe('s0')
  })

  it('소리 없음·깨진 소리·재생 시작 실패는 길이 0으로 보고 순서대로 넘어간다', async () => {
    audio.broken.add('bad')
    const { output, events } = setup()
    output.enqueue({ audio: null, index: 0 })
    output.enqueue({ audio: b64('bad'), index: 1 })
    output.enqueue({ audio: b64('s2'), index: 2 })
    await tick()
    expect(nowPlaying()).toBe('s2')
    expect(events).toEqual([
      { type: 'sentence_played', index: 0 },
      { type: 'sentence_played', index: 1 },
    ])
    audio.startError = true
    await finish()
    output.enqueue({ audio: b64('s3'), index: 3 })
    await tick()
    expect(events.slice(2)).toEqual([
      { type: 'sentence_played', index: 2 },
      { type: 'playback_idle' },
      { type: 'sentence_played', index: 3 },
      { type: 'playback_idle' },
    ])
  })

  it('stop은 끝 알림이 오지 않아도 즉시 멈추고, 바로 넣은 소리를 재생한다', async () => {
    const { output, events } = setup()
    output.enqueue({ audio: b64('s0'), index: 0 })
    output.enqueue({ audio: b64('s1'), index: 1 })
    await tick()
    expect(nowPlaying()).toBe('s0')
    output.stop()
    output.enqueue({ audio: b64('next'), index: 0 }) // 기다리지 않고 바로
    await tick()
    expect(nowPlaying()).toBe('next')
    expect(events).toEqual([])
    await finish()
    expect(events).toEqual([{ type: 'sentence_played', index: 0 }, { type: 'playback_idle' }])
  })

  it('디코드 중에 stop하고 새 소리를 넣으면 새 소리만 재생하고 idle은 한 번', async () => {
    const gate = deferred()
    audio.decodeDelay.set('old', gate.promise)
    const { output, events } = setup()
    output.enqueue({ audio: b64('old'), index: 0 })
    await tick()
    output.stop()
    output.enqueue({ audio: b64('new'), index: 0 })
    gate.resolve()
    await tick()
    expect(audio.sources.map((s) => s.buffer?.id)).toEqual(['new'])
    await finish()
    expect(events).toEqual([{ type: 'sentence_played', index: 0 }, { type: 'playback_idle' }])
  })

  it('받는 쪽이 예외를 던져도 대기열은 이어진다', async () => {
    const { output, events } = setup((e) => {
      if (e.type === 'sentence_played') throw new Error('handler')
    })
    vi.spyOn(console, 'error').mockImplementation(() => {})
    output.enqueue({ audio: null, index: 0 })
    output.enqueue({ audio: null, index: 1 })
    await tick()
    expect(events).toEqual([
      { type: 'sentence_played', index: 0 },
      { type: 'sentence_played', index: 1 },
      { type: 'playback_idle' },
    ])
  })

  it('끝 알림이 오지 않으면 소리 길이 + 여유 뒤에 넘어간다', async () => {
    vi.useFakeTimers()
    const { output, events } = setup()
    output.enqueue({ audio: b64('s0'), index: 0 })
    await vi.advanceTimersByTimeAsync(0)
    expect(nowPlaying()).toBe('s0')
    await vi.advanceTimersByTimeAsync(2400) // 0.5초 + 2초 여유 전
    expect(events).toEqual([])
    await vi.advanceTimersByTimeAsync(200)
    expect(events).toEqual([{ type: 'sentence_played', index: 0 }, { type: 'playback_idle' }])
  })

  it('오디오가 멈춰 있으면 다시 켜 보고, 켜지지 않아도 오래 기다리지 않는다', async () => {
    vi.useFakeTimers()
    audio.state = 'suspended'
    audio.resume = vi.fn(() => new Promise<void>(() => {})) // 사용자 동작 밖: 영영 안 켜진다
    const { output } = setup()
    output.enqueue({ audio: b64('s0'), index: 0 })
    await vi.advanceTimersByTimeAsync(0)
    expect(audio.resume).toHaveBeenCalled()
    expect(audio.sources).toHaveLength(0)
    await vi.advanceTimersByTimeAsync(500)
    expect(nowPlaying()).toBe('s0')
  })

  it('알림음은 한 번만 받아 두고 바로 낸다', async () => {
    const fetchMock = vi.fn(async () => new Response(new TextEncoder().encode('ding')))
    vi.stubGlobal('fetch', fetchMock)
    const output = createAudioOutput(() => {}, { saved: '/sounds/saved.mp3' })
    output.playEffect('saved')
    output.playEffect('saved')
    output.playEffect('listen') // 파일이 없는 알림음은 무시
    await tick()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(audio.sources.map((s) => s.buffer?.id)).toEqual(['ding', 'ding'])
  })

  it('dispose 뒤에는 아무것도 하지 않는다', async () => {
    const { output, events } = setup()
    await output.dispose()
    output.enqueue({ audio: b64('s0'), index: 0 })
    output.playEffect('saved')
    await tick()
    expect(audio.sources).toHaveLength(0)
    expect(events).toEqual([])
  })
})
