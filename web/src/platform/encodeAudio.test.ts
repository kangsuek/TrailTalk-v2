import { describe, expect, it } from 'vitest'
import { encodeWav } from './encodeAudio'

describe('encodeWav', () => {
  it('16kHz 모노 16bit PCM WAV 헤더와 샘플을 쓴다', () => {
    const bytes = encodeWav(new Float32Array([0, 1, -1, 0.5, 2, -2]), 16000)
    const view = new DataView(bytes.buffer)
    const text = (offset: number) => String.fromCharCode(...bytes.slice(offset, offset + 4))
    expect(bytes.length).toBe(44 + 6 * 2)
    expect([text(0), text(8), text(12), text(36)]).toEqual(['RIFF', 'WAVE', 'fmt ', 'data'])
    expect(view.getUint32(4, true)).toBe(36 + 12)
    expect(view.getUint16(20, true)).toBe(1) // PCM
    expect(view.getUint16(22, true)).toBe(1) // 모노
    expect(view.getUint32(24, true)).toBe(16000)
    expect(view.getUint32(28, true)).toBe(32000)
    expect(view.getUint16(34, true)).toBe(16)
    expect(view.getUint32(40, true)).toBe(12)
    const samples = Array.from({ length: 6 }, (_, i) => view.getInt16(44 + i * 2, true))
    // 범위를 벗어난 2, -2는 1, -1로 잘린다
    expect(samples).toEqual([0, 32767, -32768, 16383, 32767, -32768])
  })
})
