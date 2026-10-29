import { describe, expect, it } from 'vitest'
import { DEFAULT_VAD_SETTINGS, type AudioInput, type AudioOutput } from '../core'
import { lazyAudioInput, lazyAudioOutput } from './lazyPlatform'

describe('음성 모듈 지연 로딩', () => {
  it('불러오기 전에 온 호출을 불러온 뒤 객체마다 같은 순서로 실행한다', async () => {
    const inputCalls: string[] = []
    const calls: string[] = [] // 재생 쪽
    let release = () => {}
    const loaded = new Promise<void>((resolve) => (release = resolve)) // 불러오기가 늦게 끝난다
    const input: AudioInput = {
      start: async () => void inputCalls.push('start'),
      stop: async () => void inputCalls.push('stop'),
      setMode: (mode) => void inputCalls.push(`mode:${mode}`),
      dispose: async () => void inputCalls.push('dispose'),
    }
    const output: AudioOutput = {
      unlock: async () => void calls.push('unlock'),
      enqueue: (item) => void calls.push(`enqueue:${item.index}`),
      stop: () => void calls.push('out-stop'),
      playEffect: (name) => void calls.push(`effect:${name}`),
      dispose: async () => void calls.push('out-dispose'),
    }
    const lazyInput = lazyAudioInput(DEFAULT_VAD_SETTINGS, () => {}, async () => {
      await loaded
      return { createAudioInput: () => input }
    })
    const lazyOutput = lazyAudioOutput(() => {}, {}, async () => {
      await loaded
      return { createAudioOutput: () => output }
    })

    const unlocked = lazyOutput.unlock()
    lazyInput.setMode('playback')
    lazyOutput.enqueue({ audio: null, index: null })
    const started = lazyInput.start()
    lazyOutput.playEffect('listen')
    expect([...inputCalls, ...calls]).toEqual([])
    release()
    await Promise.all([unlocked, started])
    expect(inputCalls).toEqual(['mode:playback', 'start'])
    expect(calls).toEqual(['unlock', 'enqueue:null', 'effect:listen'])

    // 불러온 뒤에는 바로(같은 흐름에서) 실행한다
    lazyOutput.stop()
    expect(calls.at(-1)).toBe('out-stop')
  })
})

describe('음성 모듈을 불러오지 못하면', () => {
  it('마이크는 시작할 때 vad_failed를 알리고, 재생은 소리 없이 끝난 것으로 알린다(나중에)', async () => {
    const inputEvents: unknown[] = []
    const outputEvents: unknown[] = []
    const fail = async () => {
      throw new Error('chunk')
    }
    const input = lazyAudioInput(DEFAULT_VAD_SETTINGS, (e) => inputEvents.push(e), fail)
    const output = lazyAudioOutput((e) => outputEvents.push(e), {}, fail)
    await input.start()
    expect(inputEvents).toEqual([{ type: 'error', code: 'vad_failed' }])
    await output.unlock()
    output.enqueue({ audio: 'eA==', index: 0 })
    expect(outputEvents).toEqual([]) // 넣은 쪽이 sentence를 먼저 보낼 수 있게 바로 알리지 않는다
    await new Promise((r) => setTimeout(r, 0))
    expect(outputEvents).toEqual([{ type: 'sentence_played', index: 0 }, { type: 'playback_idle' }])
    await expect(output.dispose()).resolves.toBeUndefined()
    await expect(input.dispose()).resolves.toBeUndefined()
  })
})
