import { describe, expect, it } from 'vitest'
import clientDefaults from '../../../shared/client-defaults.json'
import { DEFAULT_VAD_SETTINGS, vadSettingsFrom } from './audio'

describe('VAD 설정', () => {
  it('서버 client.vad(snake_case)를 그대로 옮긴다', () => {
    expect(
      vadSettingsFrom({
        speech_threshold: 0.6,
        silence_threshold: 0.4,
        playback_speech_threshold: 0.9,
        playback_silence_threshold: 0.7,
        end_of_speech_silence_ms: 1000,
        min_speech_ms: 250,
      }),
    ).toEqual({
      speechThreshold: 0.6,
      silenceThreshold: 0.4,
      playbackSpeechThreshold: 0.9,
      playbackSilenceThreshold: 0.7,
      endOfSpeechSilenceMs: 1000,
      minSpeechMs: 250,
    })
  })

  it('대체값은 shared/client-defaults.json이다', () => {
    expect(DEFAULT_VAD_SETTINGS.speechThreshold).toBe(clientDefaults.vad.speech_threshold)
    expect(DEFAULT_VAD_SETTINGS.endOfSpeechSilenceMs).toBe(clientDefaults.vad.end_of_speech_silence_ms)
  })
})
