import { existsSync, statSync } from 'node:fs'
import { basename } from 'node:path'
import { describe, expect, it } from 'vitest'
import { VAD_ASSETS, VAD_DIR } from '../vadAssets.ts'

declare const __VAD_DIR__: string // vite.config.ts의 define

// 음성 감지(VAD)는 CDN이 아니라 앱이 서빙하는 자산을 쓴다(vite.config.ts의 vadAssets 플러그인).
describe('VAD 자산', () => {
  it('버전 폴더 이름에 패키지 버전이 들어 있다', () => {
    expect(VAD_DIR).toMatch(/^vad\/\d+\.\d+\.\d+-\d+\.\d+\.\d+\/$/)
  })

  it('모델·worklet·wasm 4개가 모두 있고 비어 있지 않다', () => {
    expect(VAD_ASSETS.map((path) => basename(path)).sort()).toEqual([
      'ort-wasm-simd-threaded.mjs',
      'ort-wasm-simd-threaded.wasm',
      'silero_vad_v5.onnx',
      'vad.worklet.bundle.min.js',
    ])
    for (const path of VAD_ASSETS) {
      expect(existsSync(path), path).toBe(true)
      expect(statSync(path).size, path).toBeGreaterThan(1000)
    }
  })

  it('앱 코드가 쓰는 자산 폴더(__VAD_DIR__)가 빌드가 내는 폴더와 같다', () => {
    expect(__VAD_DIR__).toBe(VAD_DIR)
  })
})
