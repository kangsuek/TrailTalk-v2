// 마이크 입력(AudioInput) 약속과 VAD 설정값(설계서 4.8, 계획서 S3-10, 클라이언트 규약 5절).
// 브라우저 구현은 src/platform/audioInput.ts. 테스트에서는 가짜 구현을 끼운다.
import clientDefaults from '../../../shared/client-defaults.json'

/** VAD 설정(서버 /api/profile의 client.vad). 확률 임계값은 Silero VAD 출력 기준이다. */
export interface VadSettings {
  speechThreshold: number
  silenceThreshold: number
  playbackSpeechThreshold: number // 캐릭터 음성 재생 중(setVadMode playback)
  playbackSilenceThreshold: number
  endOfSpeechSilenceMs: number // 무음이 이만큼 이어지면 발화 끝
  minSpeechMs: number // 이보다 짧은 소리는 버린다
}

/** 서버 client.vad(snake_case)와 같은 모양 */
export interface ClientVadConfig {
  speech_threshold: number
  silence_threshold: number
  playback_speech_threshold: number
  playback_silence_threshold: number
  end_of_speech_silence_ms: number
  min_speech_ms: number
}

export function vadSettingsFrom(vad: ClientVadConfig): VadSettings {
  return {
    speechThreshold: vad.speech_threshold,
    silenceThreshold: vad.silence_threshold,
    playbackSpeechThreshold: vad.playback_speech_threshold,
    playbackSilenceThreshold: vad.playback_silence_threshold,
    endOfSpeechSilenceMs: vad.end_of_speech_silence_ms,
    minSpeechMs: vad.min_speech_ms,
  }
}

// 프로필을 받기 전 대체값(shared/client-defaults.json)
export const DEFAULT_VAD_SETTINGS: VadSettings = vadSettingsFrom(clientDefaults.vad)

export type VadMode = 'normal' | 'playback'

/** 말 한 번의 녹음. 서버 음성 턴(POST /api/sessions/{id}/turns/audio) 본문으로 그대로 보낸다 */
export interface RecordedAudio {
  bytes: Uint8Array<ArrayBuffer>
  mimeType: string // 'audio/webm;codecs=opus' 또는 대체 형식 'audio/wav'
  durationMs: number
}

export type AudioInputErrorCode = 'mic_denied' | 'mic_unavailable' | 'vad_failed'

// speech_start는 말소리가 minSpeechMs 동안 이어진 뒤에 온다(더 짧은 소리는 이벤트 없이 버린다).
// stop·dispose 뒤에는 아무 이벤트도 오지 않는다
export type AudioInputEvent =
  // rawStartAt: vad-web이 말소리를 처음 잡은 시각(확정 전, 단조 시계 ms). 끼어들기 기록의 감지 → 확정 지연
  | { type: 'speech_start'; rawStartAt?: number }
  // speechEndedAt: 말소리가 실제로 끝난 시각(무음 대기 전, 단조 시계 ms). 지연 측정(S3-07)
  | { type: 'speech_end'; audio: RecordedAudio; speechEndedAt: number }
  | { type: 'error'; code: AudioInputErrorCode }

/** 상태 머신 명령과 1:1: micOn → start, micOff → stop, setVadMode → setMode */
export interface AudioInput {
  start(): Promise<void>
  stop(): Promise<void>
  setMode(mode: VadMode): void
  dispose(): Promise<void>
}

export type SoundName = 'listen' | 'saved' | 'offline'

/** 재생 대기열에 넣는 소리. index: 답변 문장 번호(인사말·검색 안내·마무리 멘트는 null) */
export interface PlaybackItem {
  audio: string | null // base64 MP3. null이면(합성 실패) 길이 0으로 보고 순서대로 넘어간다
  index: number | null
}

// sentence_played: 그 문장을 끝까지 들려줬다. playback_idle: 보내는 순간 대기열이 비어 있다(규약 4절).
// started: 소리 하나가 재생을 시작했다(지연 측정용, 상태 머신에는 넘기지 않는다)
export type AudioOutputEvent =
  | { type: 'sentence_played'; index: number }
  | { type: 'playback_idle' }
  | { type: 'started'; index: number | null }

/** 답변 소리 이어 재생. 상태 머신 명령 stopPlayback → stop, playSound → playEffect */
export interface AudioOutput {
  unlock(): Promise<void> // 사용자 동작(버튼) 안에서 불러 소리를 낼 수 있게 한다
  enqueue(item: PlaybackItem): void
  stop(): void // 즉시 멈추고 대기열을 비운다(이벤트를 보내지 않는다)
  playEffect(name: SoundName): void // 알림음. 대기열과 상관없이 바로 낸다
  dispose(): Promise<void>
}
