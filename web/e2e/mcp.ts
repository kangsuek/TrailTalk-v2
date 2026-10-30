import { createHash, randomBytes } from 'node:crypto'

// 외부 MCP 서버(Claude 앱 연계)를 OAuth로 연결해 도구를 부르는 시험용 클라이언트.
// 실제 Claude 앱 대신 같은 프로토콜(DCR → 인가 → 소유자 로그인 → PKCE 코드 교환 → JSON-RPC)을 쓴다.
const BASE = 'http://127.0.0.1:8401'
const PUBLIC = 'http://localhost:8401'
const CALLBACK = 'https://claude.ai/api/mcp/auth_callback'
const PASSWORD = 'e2e-owner-password-1234'

export interface McpClient {
  call(name: string, args?: Record<string, unknown>): Promise<{ isError: boolean; text: string }>
}

export async function connectMcp(): Promise<McpClient> {
  const registered = await fetch(`${BASE}/register`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      redirect_uris: [CALLBACK],
      token_endpoint_auth_method: 'none',
      grant_types: ['authorization_code', 'refresh_token'],
      response_types: ['code'],
      client_name: 'E2E Claude',
    }),
  })
  const { client_id: clientId } = (await registered.json()) as { client_id: string }

  const verifier = randomBytes(48).toString('base64url')
  const challenge = createHash('sha256').update(verifier).digest('base64url')
  const authorize = new URL(`${BASE}/authorize`)
  for (const [k, v] of Object.entries({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: CALLBACK,
    code_challenge: challenge,
    code_challenge_method: 'S256',
    state: 'e2e',
    scope: 'mcp offline_access',
    resource: `${PUBLIC}/mcp`,
  })) {
    authorize.searchParams.set(k, v)
  }
  const pending = await fetch(authorize, { redirect: 'manual' })
  const loginPath = pending.headers.get('location') ?? ''
  const req = new URL(loginPath, BASE).searchParams.get('req') ?? ''

  const login = await fetch(`${BASE}/login`, {
    method: 'POST',
    redirect: 'manual',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ req, password: PASSWORD }),
  })
  const code = new URL(login.headers.get('location') ?? '').searchParams.get('code') ?? ''

  const tokenResponse = await fetch(`${BASE}/token`, {
    method: 'POST',
    headers: { 'content-type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({
      grant_type: 'authorization_code',
      client_id: clientId,
      code,
      redirect_uri: CALLBACK,
      code_verifier: verifier,
    }),
  })
  const { access_token: token } = (await tokenResponse.json()) as { access_token: string }

  let id = 0
  return {
    async call(name, args = {}) {
      const response = await fetch(`${BASE}/mcp`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          accept: 'application/json, text/event-stream',
          authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          jsonrpc: '2.0',
          id: ++id,
          method: 'tools/call',
          params: { name, arguments: args },
        }),
      })
      const { result } = (await response.json()) as {
        result: { isError?: boolean; content: { type: string; text: string }[] }
      }
      const text = result.content.map((part) => part.text).join('')
      return { isError: result.isError ?? false, text }
    },
  }
}
