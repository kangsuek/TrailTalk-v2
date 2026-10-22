import { defineConfig } from '@playwright/test'

// E2E는 임시 폴더(web/.e2e/data)의 DB·첨부·오디오·CLI 폴더로 격리 서버(8100)를 띄운다.
// 사용자의 실제 서버(8000)와 DB(server/data)는 건드리지 않는다(CLAUDE.md).
const API_PORT = 8100
const WEB_PORT = 5174
const DATA_DIR = '.e2e/data'

export default defineConfig({
  testDir: 'e2e',
  // 스크린샷 기준 이미지는 OS마다 다르게 그려지므로 플랫폼별 폴더에 둔다
  snapshotPathTemplate: '{testDir}/__screenshots__/{platform}/{testFilePath}/{arg}{ext}',
  use: { baseURL: `http://127.0.0.1:${WEB_PORT}`, viewport: { width: 360, height: 800 } },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
  webServer: [
    {
      command:
        `rm -rf ${DATA_DIR} && mkdir -p ${DATA_DIR} && cd ../server && ` +
        `DATABASE_URL="sqlite+aiosqlite:///$PWD/../web/${DATA_DIR}/trailtalk.db" ` +
        `ATTACHMENTS_DIR="$PWD/../web/${DATA_DIR}/attachments" ` +
        `AUDIO_DIR="$PWD/../web/${DATA_DIR}/audio" ` +
        `CLI_WORK_DIR="$PWD/../web/${DATA_DIR}/cli" ` +
        `WEB_DIST_DIR="$PWD/../web/${DATA_DIR}/no-dist" ` +
        `uv run uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      env: { VITE_API_TARGET: `http://127.0.0.1:${API_PORT}` },
      reuseExistingServer: false,
      timeout: 60_000,
    },
  ],
})
