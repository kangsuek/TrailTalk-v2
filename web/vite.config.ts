/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs'
import { basename } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig, type Plugin } from 'vite'
import { VAD_ASSETS, VAD_DIR } from './vadAssets.ts'

const CONTENT_TYPES: Record<string, string> = {
  '.js': 'text/javascript',
  '.mjs': 'text/javascript',
  '.wasm': 'application/wasm',
  '.onnx': 'application/octet-stream',
}

// 음성 감지(VAD) 모델·worklet·wasm은 CDN이 아니라 앱이 서빙한다(오프라인·산에서도 동작해야 한다).
// 개발 서버는 미들웨어로, 빌드는 산출물(dist/vad/<버전>/)로 낸다
function vadAssets(): Plugin {
  const byName = new Map(VAD_ASSETS.map((path) => [basename(path), path]))
  return {
    name: 'vad-assets',
    configureServer(server) {
      // 앱은 BASE_URL + VAD_DIR(버전 폴더)을 요청한다(src/platform/audioInput.ts)
      server.middlewares.use(`${server.config.base}${VAD_DIR}`, (req, res, next) => {
        const path = byName.get((req.url ?? '').split('?')[0].replace(/^\//, ''))
        if (!path) return next()
        res.setHeader('Content-Type', CONTENT_TYPES[path.slice(path.lastIndexOf('.'))])
        res.end(readFileSync(path))
      })
    },
    generateBundle() {
      for (const [name, path] of byName) {
        this.emitFile({ type: 'asset', fileName: `${VAD_DIR}${name}`, source: readFileSync(path) })
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), vadAssets()],
  define: { __VAD_DIR__: JSON.stringify(VAD_DIR) },
  // 음성 모듈은 나중에 불러오므로, 처음 쓸 때 개발 서버가 의존성을 다시 묶으며 페이지를 새로 고치지 않게 한다
  optimizeDeps: { include: ['@ricky0123/vad-web', 'mediabunny'] },
  // 음성 모듈 청크(platform, 화면이 열린 뒤 따로 불러온다)가 약 550KB다
  build: { chunkSizeWarningLimit: 600 },
  server: {
    // 개발 중 /api 요청은 FastAPI(uvicorn, 기본 8000번)로 넘긴다.
    // 검증용 서버를 따로 띄울 때는 VITE_API_TARGET으로 그 주소를 준다(예: 격리 서버 8100번).
    proxy: { '/api': process.env.VITE_API_TARGET ?? 'http://127.0.0.1:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    include: ['src/**/*.test.{ts,tsx}', 'tests/**/*.test.ts'],
  },
})
