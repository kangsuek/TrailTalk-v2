import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { AudioInputEvent } from '../core/audio'
import { DEFAULT_VAD_SETTINGS } from '../core/audio'

type Options = Record<string, unknown> & {
  getStream: () => Promise<unknown>
  onSpeechStart: () => void
  onVADMisfire: () => void
  onSpeechRealStart: () => void
  onSpeechEnd: (samples: Float32Array) => Promise<void>
}
type Spy = ReturnType<typeof vi.fn>
interface FakeVad {
  errored: string | null
  start: Spy
  pause: Spy
  destroy: Spy
  setOptions: Spy
}

const fake = vi.hoisted(() => ({
  created: [] as { options: Options; vad: FakeVad }[],
  startError: null as Error | null,
  gate: null as Promise<void> | null, // 있으면 MicVAD.new가 이 promise를 기다린다(불러오는 중 상황)
  creating: 0, // MicVAD.new가 불린 횟수
}))

vi.mock('@ricky0123/vad-web', () => ({
  MicVAD: {
    new: vi.fn(async (options: Options) => {
      fake.creating += 1
      if (fake.gate) await fake.gate
      const vad: FakeVad = {
        errored: null,
        start: vi.fn(async () => {
          await options.getStream()
          if (fake.startError) {
            vad.errored = fake.startError.message
            throw fake.startError
          }
        }),
        pause: vi.fn(async () => {}),
        destroy: vi.fn(async () => {}),
        setOptions: vi.fn(),
      }
      fake.created.push({ options, vad })
      return vad
    }),
  },
}))

vi.mock('./encodeAudio', () => ({
  encodeUtterance: vi.fn(async (samples: Float32Array, rate: number) => ({
    bytes: new Uint8Array(3),
    mimeType: 'audio/webm;codecs=opus',
    durationMs: Math.round((samples.length / rate) * 1000),
  })),
}))

const { createAudioInput } = await import('./audioInput')

// jsdom에는 마이크와 오디오 컨텍스트가 없어 흉내 낸다
const mic = { tracks: [] as { stop: Spy }[], error: null as Error | null }
const contexts: { close: Spy }[] = []
const getUserMedia = vi.fn(async () => {
  if (mic.error) throw mic.error
  const track = { stop: vi.fn() }
  mic.tracks.push(track)
  return { getTracks: () => [track] }
})

beforeEach(() => {
  fake.created.length = 0
  fake.startError = null
  fake.gate = null
  fake.creating = 0
  mic.tracks.length = 0
  mic.error = null
  contexts.length = 0
  getUserMedia.mockClear()
  Object.defineProperty(navigator, 'mediaDevices', { value: { getUserMedia }, configurable: true })
  vi.stubGlobal(
    'AudioContext',
    class {
      close = vi.fn(async () => {})
      constructor() {
        contexts.push(this)
      }
    },
  )
})

afterEach(() => vi.unstubAllGlobals())

function setup() {
  const events: AudioInputEvent[] = []
  const input = createAudioInput(DEFAULT_VAD_SETTINGS, (e) => events.push(e))
  return { input, events }
}

function deferred() {
  let resolve = () => {}
  const promise = new Promise<void>((r) => (resolve = r))
  return { promise, resolve }
}

describe('createAudioInput', () => {
  it('처음 start에 마이크를 열고 VAD를 서버 설정값으로 만든다. 이후에는 다시 연다', async () => {
    const { input } = setup()
    await input.start()
    await input.stop()
    await input.start()
    expect(fake.created).toHaveLength(1)
    const { options, vad } = fake.created[0]
    expect(options).toMatchObject({
      model: 'v5',
      startOnLoad: false,
      baseAssetPath: `/${__VAD_DIR__}`,
      onnxWASMBasePath: `/${__VAD_DIR__}`,
      audioContext: contexts[0],
      positiveSpeechThreshold: DEFAULT_VAD_SETTINGS.speechThreshold,
      negativeSpeechThreshold: DEFAULT_VAD_SETTINGS.silenceThreshold,
      redemptionMs: DEFAULT_VAD_SETTINGS.endOfSpeechSilenceMs,
      minSpeechMs: DEFAULT_VAD_SETTINGS.minSpeechMs,
    })
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    expect(vad.start).toHaveBeenCalledTimes(2)
    expect(vad.pause).toHaveBeenCalledTimes(1)
  })

  it('재생 중에는 임계값을 올리고 평상시로 되돌린다', async () => {
    const { input } = setup()
    await input.start()
    const { vad } = fake.created[0]
    input.setMode('playback')
    input.setMode('normal')
    expect(vad.setOptions).toHaveBeenNthCalledWith(1, {
      positiveSpeechThreshold: DEFAULT_VAD_SETTINGS.playbackSpeechThreshold,
      negativeSpeechThreshold: DEFAULT_VAD_SETTINGS.playbackSilenceThreshold,
    })
    expect(vad.setOptions).toHaveBeenNthCalledWith(2, {
      positiveSpeechThreshold: DEFAULT_VAD_SETTINGS.speechThreshold,
      negativeSpeechThreshold: DEFAULT_VAD_SETTINGS.silenceThreshold,
    })
  })

  it('불러오기 전에 바꾼 모드는 VAD를 만들 때 반영한다', async () => {
    const { input } = setup()
    input.setMode('playback')
    await input.start()
    expect(fake.created[0].options.positiveSpeechThreshold).toBe(
      DEFAULT_VAD_SETTINGS.playbackSpeechThreshold,
    )
  })

  it('말소리가 이어진 뒤에 speech_start, 말이 끝나면 인코딩한 speech_end를 넘긴다', async () => {
    const { input, events } = setup()
    await input.start()
    const { options } = fake.created[0]
    // 첫 프레임 감지(onSpeechStart)·짧은 소리(onVADMisfire)는 상태 머신에 알리지 않는다(계측만)
    const now = vi.spyOn(performance, 'now').mockReturnValue(4760)
    options.onSpeechStart()
    options.onVADMisfire()
    expect(events).toEqual([])
    options.onSpeechStart()
    options.onSpeechRealStart()
    now.mockReturnValue(5000)
    await options.onSpeechEnd(new Float32Array(16000))
    expect(events).toEqual([
      { type: 'speech_start', rawStartAt: 4760 },
      {
        type: 'speech_end',
        audio: { bytes: new Uint8Array(3), mimeType: 'audio/webm;codecs=opus', durationMs: 1000 },
        // 끝을 알아채기까지 기다린 무음만큼 앞이 실제 말 끝이다
        speechEndedAt: 5000 - DEFAULT_VAD_SETTINGS.endOfSpeechSilenceMs,
      },
    ])
    vi.restoreAllMocks()
  })

  it('stop 뒤에는 늦게 끝난 발화도 넘기지 않는다', async () => {
    const { input, events } = setup()
    await input.start()
    const { options } = fake.created[0]
    const ending = options.onSpeechEnd(new Float32Array(160))
    await input.stop()
    await ending
    options.onSpeechRealStart()
    expect(events).toEqual([])
  })

  it('VAD를 만드는 중에 stop이 오면 마이크를 듣지 않는다', async () => {
    const gate = deferred()
    fake.gate = gate.promise
    const { input } = setup()
    const started = input.start()
    await vi.waitFor(() => expect(fake.creating).toBe(1)) // 마이크를 열고 MicVAD.new를 기다리는 중
    const stopped = input.stop()
    gate.resolve()
    await Promise.all([started, stopped])
    expect(fake.created).toHaveLength(1)
    expect(fake.created[0].vad.start).not.toHaveBeenCalled()
    expect(mic.tracks[0].stop).toHaveBeenCalled() // 미리 연 마이크도 닫는다

    // 다음 start는 만든 VAD를 그대로 쓰고 마이크를 새로 연다
    await input.start()
    expect(fake.created).toHaveLength(1)
    expect(fake.created[0].vad.start).toHaveBeenCalledTimes(1)
    expect(mic.tracks).toHaveLength(2)
    expect(mic.tracks[1].stop).not.toHaveBeenCalled()
  })

  it('VAD를 만드는 중에 dispose하면 마이크·컨텍스트·VAD를 정리한다', async () => {
    const gate = deferred()
    fake.gate = gate.promise
    const { input } = setup()
    const started = input.start()
    await vi.waitFor(() => expect(fake.creating).toBe(1))
    const disposed = input.dispose()
    gate.resolve()
    await Promise.all([started, disposed])
    expect(fake.created[0].vad.start).not.toHaveBeenCalled()
    expect(fake.created[0].vad.destroy).toHaveBeenCalled()
    expect(mic.tracks[0].stop).toHaveBeenCalled()
    expect(contexts[0].close).toHaveBeenCalled()
  })

  it('권한 거부는 모델을 불러오기 전에 mic_denied로 알리고, 다음 start에 다시 시도한다', async () => {
    const { input, events } = setup()
    mic.error = new DOMException('denied', 'NotAllowedError')
    await input.start()
    expect(events).toEqual([{ type: 'error', code: 'mic_denied' }])
    expect(fake.created).toHaveLength(0)

    mic.error = null
    await input.start()
    expect(fake.created).toHaveLength(1)
    expect(fake.created[0].vad.start).toHaveBeenCalled()
    expect(events).toHaveLength(1)
  })

  it('HTTPS가 아니어서 mediaDevices가 없으면 mic_unavailable', async () => {
    Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true })
    const { input, events } = setup()
    await input.start()
    expect(events).toEqual([{ type: 'error', code: 'mic_unavailable' }])
  })

  it('권한 창을 기다리는 사이 stop이 오면 거부 오류를 알리지 않는다', async () => {
    let deny = () => {}
    getUserMedia.mockImplementationOnce(
      () => new Promise((_, reject) => (deny = () => reject(new DOMException('denied', 'NotAllowedError')))),
    )
    const { input, events } = setup()
    const started = input.start()
    await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalled())
    const stopped = input.stop()
    deny()
    await Promise.all([started, stopped])
    expect(events).toEqual([])
  })

  it('장치가 없으면 mic_unavailable', async () => {
    const { input, events } = setup()
    mic.error = new DOMException('none', 'NotFoundError')
    await input.start()
    expect(events).toEqual([{ type: 'error', code: 'mic_unavailable' }])
  })

  it('VAD 시작 실패는 vad_failed로 알리고 마이크·컨텍스트를 닫은 뒤 다음 start에 새로 만든다', async () => {
    const { input, events } = setup()
    fake.startError = new Error('worklet')
    await input.start()
    expect(events).toEqual([{ type: 'error', code: 'vad_failed' }])
    expect(fake.created[0].vad.destroy).toHaveBeenCalled()
    expect(mic.tracks[0].stop).toHaveBeenCalled()
    expect(contexts[0].close).toHaveBeenCalled()

    fake.startError = null
    await input.start()
    expect(fake.created).toHaveLength(2)
    expect(events).toHaveLength(1)
  })

  it('dispose 뒤에는 늦게 끝난 발화를 넘기지 않는다', async () => {
    const { input, events } = setup()
    await input.start()
    const { options, vad } = fake.created[0]
    await input.dispose()
    await options.onSpeechEnd(new Float32Array(160))
    expect(events).toEqual([])
    expect(vad.destroy).toHaveBeenCalled()
  })
})
