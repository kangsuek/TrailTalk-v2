// AudioOutput 브라우저 구현(규약 6.6, 계획 M3-11): Web Audio API로 문장 MP3를 차례로 이어 재생한다.
// 소리가 없는 문장(합성 실패)은 서버가 보낸 speech_text를 기기 TTS(speechSynthesis, ko-KR)로 읽는다.
// 넣는 즉시 디코드를 시작해(병렬) 문장 사이 공백을 줄이고, 재생은 넣은 순서대로 하나씩 한다.
// 어떤 경우에도 대기열이 멈추지 않게 한다: 소리가 안 나는 상황(자동 재생 제한, 오디오 중단)에서도
// 이벤트는 차례로 나가 대화가 이어진다.
import type { AudioOutput, AudioOutputEvent, PlaybackItem, SoundName } from '../core/audio'
import { metrics } from './metrics'

interface Queued {
  index: number | null
  buffer: Promise<AudioBuffer | null>
  speechText: string | null
}

/** 기기 TTS로 글을 읽는다. done은 다 읽거나 읽지 못하면 끝나고(대기열이 멈추지 않게), cancel은 즉시 멈춘다. */
export interface DeviceSpeech {
  done: Promise<void>
  cancel(): void
}

export type SpeakOnDevice = (text: string) => DeviceSpeech

const SPEAK_BASE_MS = 3000 // 읽기 끝 알림이 오지 않을 때를 위한 상한: 기본 시간 + 글자당 시간
const SPEAK_PER_CHAR_MS = 500

export const speakOnDevice: SpeakOnDevice = (text) => {
  const synth = globalThis.speechSynthesis
  if (!synth || typeof SpeechSynthesisUtterance === 'undefined') return { done: Promise.resolve(), cancel() {} }
  let finish: () => void = () => {}
  const done = new Promise<void>((resolve) => {
    finish = resolve
  })
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = 'ko-KR'
  utterance.onend = finish
  utterance.onerror = finish
  const timer = setTimeout(finish, SPEAK_BASE_MS + text.length * SPEAK_PER_CHAR_MS)
  void done.then(() => clearTimeout(timer))
  try {
    synth.speak(utterance)
  } catch {
    finish()
  }
  return {
    done,
    cancel() {
      try {
        synth.cancel()
      } catch {
        // 이미 끝났다
      }
      finish()
    },
  }
}

const RESUME_WAIT_MS = 500 // 멈춘 오디오를 다시 켜기를 기다리는 시간(사용자 동작 밖이면 영영 안 켜진다)
const ENDED_GRACE_MS = 2000 // 재생 끝 알림(onended)이 소리 길이보다 이만큼 늦으면 끝난 것으로 본다

function bytesOf(base64: string): ArrayBuffer {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i)
  return bytes.buffer
}

/** effects: 알림음 이름 → 파일 URL(shared/sounds) */
export function createAudioOutput(
  onEvent: (event: AudioOutputEvent) => void,
  effects: Partial<Record<SoundName, string>> = {},
  speak: SpeakOnDevice = speakOnDevice,
): AudioOutput {
  let context: AudioContext | null = null
  let generation = 0 // stop()마다 올려서 그 전에 시작한 디코드·재생의 결과를 버린다
  let queue: Queued[] = []
  let playing: { source: AudioBufferSourceNode; index: number | null; finish: () => void } | null = null
  let reading: DeviceSpeech | null = null // 지금 기기 TTS로 읽는 중인 문장
  let pumping = false
  let disposed = false
  const effectBuffers = new Map<SoundName, Promise<AudioBuffer | null>>()

  const audioContext = () => (context ??= new AudioContext())

  const emit = (event: AudioOutputEvent) => {
    try {
      onEvent(event)
    } catch (error) {
      console.error('재생 이벤트 처리 실패', error) // 받는 쪽 오류로 대기열이 멈추지 않게 한다
    }
  }

  const decode = async (data: ArrayBuffer | null): Promise<AudioBuffer | null> => {
    if (!data || disposed) return null
    try {
      return await audioContext().decodeAudioData(data)
    } catch {
      return null // 깨진 소리는 건너뛴다(문장 번호는 그대로 보고한다)
    }
  }

  const ready = async (ctx: AudioContext) => {
    if (ctx.state === 'running') return
    await Promise.race([
      ctx.resume().catch(() => {}),
      new Promise((resolve) => setTimeout(resolve, RESUME_WAIT_MS)),
    ])
  }

  /** 끝까지 재생하거나, stop()되거나, 끝 알림이 오지 않으면 길이 + 여유 뒤에 끝난다 */
  const play = (buffer: AudioBuffer, index: number | null) =>
    new Promise<void>((resolve) => {
      const ctx = audioContext()
      const source = ctx.createBufferSource()
      let timer: ReturnType<typeof setTimeout> | undefined
      const finish = () => {
        clearTimeout(timer)
        if (playing?.source === source) playing = null
        resolve()
      }
      source.buffer = buffer
      source.onended = finish
      playing = { source, index, finish }
      try {
        source.connect(ctx.destination)
        source.start()
        metrics.mark('playback_start', { index })
        emit({ type: 'started', index })
        // 오디오가 멈춰 끝 알림이 오지 않으면 넘어간다. 나중에 다시 켜져도 겹치지 않게 그 소리는 멈춘다
        timer = setTimeout(() => {
          try {
            source.stop()
            source.disconnect()
          } catch {
            // 이미 끝났다
          }
          finish()
        }, buffer.duration * 1000 + ENDED_GRACE_MS)
      } catch {
        finish() // 재생하지 못한 소리도 길이 0으로 보고 넘어간다
      }
    })

  const pump = async () => {
    if (pumping) return
    pumping = true
    const current = generation
    try {
      while (queue.length > 0 && current === generation) {
        const item = queue[0]
        const buffer = await item.buffer
        if (current !== generation) break
        if (buffer) {
          await ready(audioContext())
          if (current !== generation) break
          await play(buffer, item.index)
        } else if (item.speechText) {
          // 합성 실패 문장: 글을 기기 TTS로 읽는다(읽기에 실패하면 길이 0으로 넘어간다)
          metrics.mark('playback_start', { index: item.index, device: true })
          emit({ type: 'started', index: item.index })
          const speech = (reading = speak(item.speechText))
          await speech.done
          if (reading === speech) reading = null
        }
        if (current !== generation) break
        queue.shift()
        if (item.index !== null) emit({ type: 'sentence_played', index: item.index })
      }
    } finally {
      pumping = false
    }
    // 멈춘 사이에 새로 들어온 소리가 있으면 이어서 재생한다
    if (queue.length > 0) return void pump()
    if (current === generation && !disposed) emit({ type: 'playback_idle' })
  }

  const stop = () => {
    generation += 1
    queue = []
    const current = playing
    playing = null
    reading?.cancel() // 기기 TTS로 읽던 문장도 멈춘다
    reading = null
    if (current) {
      try {
        current.source.stop()
        metrics.mark('source_stop', { index: current.index })
      } catch {
        // 이미 끝났거나 시작 전이다
      }
      current.finish() // 끝 알림(onended)이 오지 않아도 바로 다음으로 넘어간다
    }
  }

  return {
    async unlock() {
      if (disposed) return
      await ready(audioContext())
    },
    enqueue(item: PlaybackItem) {
      if (disposed) return
      queue.push({
        index: item.index,
        buffer: decode(item.audio ? bytesOf(item.audio) : null),
        speechText: item.audio ? null : (item.speechText ?? null),
      })
      void pump()
    },
    stop,
    playEffect(name: SoundName) {
      const url = effects[name]
      if (!url || disposed) return
      let buffer = effectBuffers.get(name)
      if (!buffer) {
        buffer = fetch(url)
          .then((response) => response.arrayBuffer())
          .then(decode, () => null)
        effectBuffers.set(name, buffer)
      }
      void buffer.then((decoded) => {
        if (!decoded || disposed) return
        try {
          const source = audioContext().createBufferSource()
          source.buffer = decoded
          source.connect(audioContext().destination)
          source.start()
        } catch {
          // 알림음은 못 내도 대화에는 지장이 없다
        }
      })
    },
    async dispose() {
      disposed = true
      stop()
      await context?.close().catch(() => {})
      context = null
    },
  }
}
