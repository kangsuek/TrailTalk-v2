// 발화 오디오 인코딩(클라이언트 규약 5절, 계획 M3-10). VAD가 준 16kHz 모노 Float32를
// WebCodecs Opus(webm)로 담고, 브라우저가 Opus 인코딩을 못 하면 WAV(16bit PCM)로 만든다.
// 서버는 webm·wav를 변환 없이 그대로 음성 인식에 넘긴다.
import {
  AudioSample,
  AudioSampleSource,
  BufferTarget,
  canEncodeAudio,
  Output,
  Quality,
  WebMOutputFormat,
} from 'mediabunny'
import type { RecordedAudio } from '../core/audio'

const OPUS_BITRATE = 24_000 // 말소리에 충분하고 업로드가 작다(서버 변환도 24kbps)

/** 16bit PCM 모노 WAV. 범위를 벗어난 샘플은 잘라 낸다 */
export function encodeWav(samples: Float32Array, sampleRate: number): Uint8Array<ArrayBuffer> {
  const bytes = new Uint8Array(44 + samples.length * 2)
  const view = new DataView(bytes.buffer)
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i))
  }
  text(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  text(8, 'WAVE')
  text(12, 'fmt ')
  view.setUint32(16, 16, true) // fmt 청크 크기
  view.setUint16(20, 1, true) // PCM
  view.setUint16(22, 1, true) // 모노
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true) // 초당 바이트
  view.setUint16(32, 2, true) // 블록 정렬
  view.setUint16(34, 16, true) // 비트
  text(36, 'data')
  view.setUint32(40, samples.length * 2, true)
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true)
  }
  return bytes
}

async function encodeOpus(
  samples: Float32Array,
  sampleRate: number,
): Promise<Uint8Array<ArrayBuffer> | null> {
  const quality = new Quality({ bitrate: OPUS_BITRATE }) // 숫자만 주면 비트레이트가 아니라 품질 배수다
  if (!(await canEncodeAudio('opus', { numberOfChannels: 1, sampleRate, quality }))) return null
  const target = new BufferTarget()
  const output = new Output({ format: new WebMOutputFormat(), target })
  const source = new AudioSampleSource({ codec: 'opus', quality })
  output.addAudioTrack(source)
  await output.start()
  const sample = new AudioSample({
    data: samples,
    format: 'f32',
    numberOfChannels: 1,
    sampleRate,
    timestamp: 0,
  })
  try {
    await source.add(sample)
  } finally {
    sample.close()
  }
  await output.finalize()
  return target.buffer ? new Uint8Array(target.buffer) : null
}

/** 말 한 번을 업로드 형식으로 만든다. Opus가 안 되면(미지원·실패) WAV */
export async function encodeUtterance(
  samples: Float32Array,
  sampleRate: number,
): Promise<RecordedAudio> {
  const durationMs = Math.round((samples.length / sampleRate) * 1000)
  try {
    const opus = await encodeOpus(samples, sampleRate)
    if (opus) return { bytes: opus, mimeType: 'audio/webm;codecs=opus', durationMs }
  } catch (error) {
    console.warn('Opus 인코딩 실패, WAV로 보냅니다', error)
  }
  return { bytes: encodeWav(samples, sampleRate), mimeType: 'audio/wav', durationMs }
}
