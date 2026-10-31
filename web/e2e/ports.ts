// E2E 격리 서버 포트. 기본값은 8100·5174·8401이고, 개발 쪽 E2E와 겹치지 않아야 하는 백그라운드 검증
// (scripts/verify-bg.sh)은 E2E_API_PORT·E2E_WEB_PORT·E2E_MCP_PORT로 다른 포트를 준다.
export const API_PORT = Number(process.env.E2E_API_PORT ?? 8100)
export const WEB_PORT = Number(process.env.E2E_WEB_PORT ?? 5174)
export const MCP_PORT = Number(process.env.E2E_MCP_PORT ?? 8401)
