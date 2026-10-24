import { defineConfig } from '@playwright/test'

// E2E는 임시 폴더(web/.e2e/data)의 DB·첨부·오디오·CLI 폴더로 격리 서버(8100)를 띄우고, Claude CLI는
// 가짜(녹화 재생)로 바꾼다.
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
        // 실제 Claude CLI 대신 녹화를 재생하는 가짜 CLI(server/tests/fakes). 첫 사용자 메시지에는
        // save_note 도구를 쓰는 턴이 나온다. 사용자 구독 사용량이 나가지 않는다
        `CLAUDE_CLI_PATH="$PWD/tests/fakes/fake-claude" ` +
        `CLI_ENV_PASSTHROUGH="FAKE_CLAUDE_*" FAKE_CLAUDE_FIXTURE=tool_call ` +
        `INTERNAL_BASE_URL="http://127.0.0.1:${API_PORT}" CLI_TURN_TIMEOUT_S=5 ` +
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
