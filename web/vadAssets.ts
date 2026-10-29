// 음성 감지(src/platform/audioInput.ts)가 실행 중에 불러오는 파일. CDN 대신 앱이 서빙한다(vite.config.ts).
// 파일 이름에 해시가 없으므로 패키지 버전을 폴더 이름에 넣는다: 서비스 워커가 처음 쓸 때 저장해 두므로
// (CacheFirst) 버전을 올리면 새 주소로 받아야 옛 wasm과 새 코드가 섞이지 않는다(onnxruntime은 JS·wasm 버전이 같아야 한다)
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'

const require = createRequire(import.meta.url)
const vadDist = dirname(require.resolve('@ricky0123/vad-web'))
// vad-web이 쓰는 onnxruntime-web(wasm 빌드)과 같은 폴더의 wasm 파일
const ortDist = dirname(createRequire(join(vadDist, 'index.js')).resolve('onnxruntime-web/wasm'))

const versionOf = (dist: string): string =>
  (JSON.parse(readFileSync(join(dist, '..', 'package.json'), 'utf8')) as { version: string }).version

/** 앱 기준 경로(BASE_URL 뒤). 예: vad/0.0.31-1.22.0/ */
export const VAD_DIR = `vad/${versionOf(vadDist)}-${versionOf(ortDist)}/`

export const VAD_ASSETS = [
  join(vadDist, 'vad.worklet.bundle.min.js'),
  join(vadDist, 'silero_vad_v5.onnx'),
  join(ortDist, 'ort-wasm-simd-threaded.mjs'),
  join(ortDist, 'ort-wasm-simd-threaded.wasm'),
]
