// 음성 모듈(vad-web·onnxruntime·mediabunny, 압축 약 150KB)은 첫 화면 로딩에서 빼고 따로 불러온다.
// 불러오기 전에 온 호출은 불러온 뒤 같은 순서로 실행한다. 화면이 열릴 때 불러오기 시작하고,
// 다 불러오기 전에는 음성 대화 시작 버튼을 막는다(오디오는 버튼을 누른 동작 안에서 열어야 하므로).
// 불러오지 못하면(오프라인, 배포 교체) 멈추지 않고 실패를 이벤트로 알린다.
import type {
  AudioInput,
  AudioInputEvent,
  AudioOutput,
  AudioOutputEvent,
  SoundName,
  VadSettings,
} from '../core'

type Platform = typeof import('../platform')
const loadPlatform = (): Promise<Platform> => import('../platform')

/** 음성 모듈을 불러왔는지(true)·못 불러왔는지(false). 화면이 시작 버튼을 막는 데 쓴다 */
export function preloadPlatform(): Promise<boolean> {
  return loadPlatform().then(
    () => true,
    () => false,
  )
}

/** 불러온 값으로 호출을 실행한다. 앞선 호출이 기다리는 중이면 뒤에 줄을 세워 순서를 지킨다 */
function lazy<T>(load: Promise<T>) {
  let real: T | null = null
  let failed = false
  let waiting = 0
  const ready = load.then(
    (value) => {
      real = value
    },
    () => {
      failed = true
    },
  )
  return <R>(use: (value: T) => R, fallback: () => R): R | Promise<R> => {
    if (waiting === 0 && (real !== null || failed)) return real !== null ? use(real) : fallback()
    waiting += 1
    return ready.then(() => {
      waiting -= 1
      return real !== null ? use(real) : fallback()
    })
  }
}

export function lazyAudioInput(
  settings: VadSettings,
  onEvent: (event: AudioInputEvent) => void,
  load: () => Promise<Pick<Platform, 'createAudioInput'>> = loadPlatform,
): AudioInput {
  const withInput = lazy(load().then((p) => p.createAudioInput(settings, onEvent)))
  const none = async () => {}
  return {
    start: async () =>
      withInput(
        (input) => input.start(),
        async () => onEvent({ type: 'error', code: 'vad_failed' }),
      ),
    stop: async () => withInput((input) => input.stop(), none),
    setMode: (mode) => void withInput((input) => input.setMode(mode), () => {}),
    dispose: async () => withInput((input) => input.dispose(), none),
  }
}

export function lazyAudioOutput(
  onEvent: (event: AudioOutputEvent) => void,
  effects: Partial<Record<SoundName, string>>,
  load: () => Promise<Pick<Platform, 'createAudioOutput'>> = loadPlatform,
): AudioOutput {
  const withOutput = lazy(load().then((p) => p.createAudioOutput(onEvent, effects)))
  const none = async () => {}
  return {
    unlock: async () => withOutput((output) => output.unlock(), none),
    enqueue: (item) =>
      void withOutput(
        (output) => output.enqueue(item),
        // 소리 없이 들려준 것으로 본다(대화는 글로 이어진다). 넣은 쪽이 머신에 sentence를 먼저
        // 보내도록 다음 차례에 알린다(규약 4절)
        () =>
          void setTimeout(() => {
            if (item.index !== null) onEvent({ type: 'sentence_played', index: item.index })
            onEvent({ type: 'playback_idle' })
          }, 0),
      ),
    stop: () => void withOutput((output) => output.stop(), () => {}),
    playEffect: (name) => void withOutput((output) => output.playEffect(name), () => {}),
    dispose: async () => withOutput((output) => output.dispose(), none),
  }
}
