// AudioInput 브라우저 구현(계획서 S3-10, 설계서 4.1 웹 열): getUserMedia + Silero VAD(@ricky0123/vad-web).
// 말이 끝나면 16kHz 모노 오디오를 Opus(webm, 안 되면 WAV)로 만들어 speech_end로 넘긴다.
import { MicVAD } from '@ricky0123/vad-web'
import type {
  AudioInput,
  AudioInputErrorCode,
  AudioInputEvent,
  VadMode,
  VadSettings,
} from '../core/audio'
import { encodeUtterance } from './encodeAudio'
import { metrics } from './metrics'

const SAMPLE_RATE = 16_000 // VAD가 주는 발화 오디오의 샘플레이트
const PRE_SPEECH_PAD_MS = 300 // 말 시작 앞부분이 잘리지 않게 감지 전 소리를 붙인다
// 모델·worklet·onnxruntime wasm은 CDN이 아니라 이 앱이 서빙한다(vite.config.ts의 vadAssets, 버전 폴더)
const ASSET_PATH = `${import.meta.env.BASE_URL}${__VAD_DIR__}`

const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
}

function thresholds(settings: VadSettings, mode: VadMode) {
  return mode === 'playback'
    ? {
        positiveSpeechThreshold: settings.playbackSpeechThreshold,
        negativeSpeechThreshold: settings.playbackSilenceThreshold,
      }
    : {
        positiveSpeechThreshold: settings.speechThreshold,
        negativeSpeechThreshold: settings.silenceThreshold,
      }
}

const MIC_UNAVAILABLE = new Set(['NotFoundError', 'NotReadableError', 'OverconstrainedError', 'NotSupportedError'])

function errorCode(error: unknown): AudioInputErrorCode {
  const name = error instanceof DOMException || error instanceof Error ? error.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError') return 'mic_denied'
  if (MIC_UNAVAILABLE.has(name)) return 'mic_unavailable'
  return 'vad_failed'
}

/** 마이크와 VAD. 모델은 처음 start() 때 불러온다(사용자 동작 뒤에 오디오를 열어야 한다) */
export function createAudioInput(
  settings: VadSettings,
  onEvent: (event: AudioInputEvent) => void,
): AudioInput {
  let vad: MicVAD | null = null
  let context: AudioContext | null = null // VAD가 쓰는 오디오 컨텍스트(직접 만들고 닫는다)
  let stream: MediaStream | null = null // 지금 열린 마이크(VAD 정리가 실패해도 직접 멈춘다)
  let mode: VadMode = 'normal'
  let rawStartAt: number | undefined // 지금 발화의 vad-web 시작 시각(확정 전, 계측용)
  let active = false // 마지막 요청이 start인가(불러오는 중에 stop이 오면 열지 않는다)
  let disposed = false
  let pending: Promise<void> = Promise.resolve() // start·stop을 들어온 순서대로 한다
  const listening = () => active && !disposed

  const openMic = async () => {
    // HTTPS가 아닌 페이지(폰에서 http로 접속 등)에는 mediaDevices가 없다
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new DOMException('마이크는 HTTPS에서만 쓸 수 있습니다', 'NotSupportedError')
    }
    stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS)
    return stream
  }

  const create = () => {
    context = new AudioContext()
    return MicVAD.new({
      model: 'v5',
      baseAssetPath: ASSET_PATH,
      onnxWASMBasePath: ASSET_PATH,
      startOnLoad: false,
      audioContext: context,
      ...thresholds(settings, mode),
      redemptionMs: settings.endOfSpeechSilenceMs,
      minSpeechMs: settings.minSpeechMs,
      preSpeechPadMs: PRE_SPEECH_PAD_MS,
      // 처음 시작은 미리 연 마이크를 쓴다(만드는 중 stop으로 닫혔으면 새로 연다)
      getStream: async () => stream ?? openMic(),
      resumeStream: openMic,
      pauseStream: async (paused) => paused.getTracks().forEach((track) => track.stop()),
      // 계측 훅(V2-M0-05): 상태 머신에는 알리지 않는다
      onFrameProcessed: (probabilities) => metrics.frame(probabilities.isSpeech),
      onSpeechStart: () => {
        rawStartAt = performance.now()
        metrics.mark('vad_raw_start', { mode })
      },
      onVADMisfire: () => {
        rawStartAt = undefined
        metrics.mark('vad_misfire', { mode })
      },
      // 말소리가 minSpeechMs 동안 이어진 뒤에 알린다. 짧은 소음 한 번에 재생 중 답변이 끊기지 않게
      // (상태 머신은 말하기 중 speech_start를 끼어들기로 처리한다). 그보다 짧은 소리는 조용히 버린다
      onSpeechRealStart: () => {
        metrics.mark('vad_confirm', { mode })
        if (listening()) onEvent({ type: 'speech_start', rawStartAt })
      },
      onSpeechEnd: async (samples) => {
        // 끝을 알아채기까지 무음을 기다렸으므로 실제로 말이 끝난 때는 그만큼 앞이다
        const speechEndedAt = performance.now() - settings.endOfSpeechSilenceMs
        rawStartAt = undefined
        metrics.mark('vad_end', { mode, silence_ms: settings.endOfSpeechSilenceMs })
        const audio = await encodeUtterance(samples, SAMPLE_RATE)
        if (listening()) onEvent({ type: 'speech_end', audio, speechEndedAt })
      },
    })
  }

  const stopMic = () => {
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  const drop = async () => {
    const [current, mic, ctx] = [vad, stream, context]
    vad = null
    stream = null
    context = null
    // vad-web의 destroy는 오디오 연결이 다 만들어지기 전이면 예외를 던지고 정리를 건너뛴다.
    // 마이크와 오디오 컨텍스트는 직접 닫는다(그 경우 모델 메모리는 남는다)
    await current?.destroy().catch(() => {})
    mic?.getTracks().forEach((track) => track.stop())
    await ctx?.close().catch(() => {})
  }

  const open = async () => {
    if (!listening()) return
    try {
      if (!vad) {
        // 권한 거부·장치 없음은 모델을 불러오기 전에 알게 된다(실패할 때마다 모델을 새로 만들지 않게)
        await openMic()
        if (!listening()) return await drop()
        vad = await create()
      }
      if (!listening()) {
        // 만드는 중에 stop이 왔다. VAD는 두고(다음 start에 쓴다) 미리 연 마이크만 닫는다
        stopMic()
        return
      }
      await vad.start()
      // vad-web은 처음 시작이 실패하면 다시 시작할 수 없으므로 버리고 다음 start()에 새로 만든다
      if (vad.errored) throw new Error(vad.errored)
    } catch (error) {
      const wanted = listening() // 실패를 기다리는 사이 stop·dispose가 왔으면 알리지 않는다
      active = false
      await drop()
      if (wanted) onEvent({ type: 'error', code: errorCode(error) })
    }
  }

  const close = async () => {
    if (active) return
    await vad?.pause()
  }

  const enqueue = (step: () => Promise<void>) => {
    pending = pending.then(step, step)
    return pending
  }

  return {
    start() {
      active = true
      return enqueue(open)
    },
    stop() {
      active = false
      return enqueue(close)
    },
    setMode(next) {
      mode = next
      metrics.mark('vad_mode', { mode })
      vad?.setOptions(thresholds(settings, mode))
    },
    dispose() {
      disposed = true
      active = false
      return enqueue(drop)
    },
  }
}
