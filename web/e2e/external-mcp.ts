import { chmodSync, existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'

// 가짜 외부 MCP 서버(M5-14) 설정. 격리 서버(playwright.config.ts)가 MCP_SERVERS_PATH로 이 파일을 읽는다.
// 서버 설정 파일은 신뢰 경계라 파일 0600·폴더 0700이어야 한다. 비밀 값은 파일이 아니라 서버 환경 변수
// (MCP_E2E_FAKE_API_KEY)로만 넘기고, 화면·응답·DB에 나오면 안 된다.
const WEB_DIR = resolve(import.meta.dirname, '..')
const SERVER_DIR = resolve(WEB_DIR, '../server')
export const MCP_DIR = resolve(WEB_DIR, '.e2e/mcp')
export const MCP_SERVERS_PATH = resolve(MCP_DIR, 'mcp-servers.yaml')
// 가짜 서버가 호출된 도구를 한 줄씩 적는 파일(서버를 띄울 때마다 지워진다, playwright.config.ts)
export const CALL_LOG = resolve(WEB_DIR, '.e2e/data/mcp-external-calls.log')
export const FAKE_SECRET = 'e2e-fake-secret-7c41d9'
export const SERVER_NAME = 'e2e-fake'

export function writeMcpServersFile(): void {
  mkdirSync(MCP_DIR, { recursive: true, mode: 0o700 })
  chmodSync(MCP_DIR, 0o700)
  const python = resolve(SERVER_DIR, '.venv/bin/python')
  const script = resolve(SERVER_DIR, 'tests/fakes/fake_mcp.py')
  const yaml = `servers:
  - name: ${SERVER_NAME}
    command: ${python}
    args: ["${script}"]
    env:
      CALL_LOG: ${CALL_LOG}
      FAKE_API_KEY: "\${MCP_E2E_FAKE_API_KEY}"
    allowed_tools: [allowed_ping, probe, leak, leak_error, long]
    denied_tools: [denied_ping]
`
  writeFileSync(MCP_SERVERS_PATH, yaml, { mode: 0o600 })
  chmodSync(MCP_SERVERS_PATH, 0o600)
}

/** 가짜 서버가 받은 도구 호출(이름) 목록 */
export function calledTools(): string[] {
  return existsSync(CALL_LOG) ? readFileSync(CALL_LOG, 'utf8').split('\n').filter(Boolean) : []
}
