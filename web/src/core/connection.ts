// 서버 연결 상태 판정. 브라우저 API에 기대지 않는 순수 로직이다(Spec 4.3, 린트로 강제).

export type Connection = 'checking' | 'connected' | 'offline'

export interface HealthResult {
  ok: boolean
}

/** 규약 1.3: 서버 연결 확인은 30초마다 한다. */
export const HEALTH_INTERVAL_MS = 30_000

export function nextConnection(result: HealthResult): Connection {
  return result.ok ? 'connected' : 'offline'
}

// 색만으로 구분하지 않도록 아이콘·문구를 함께 쓴다(시안 대화 10 기초 화면)
export const CONNECTION_LABEL: Record<Connection, { icon: string; text: string }> = {
  checking: { icon: '…', text: '확인 중' },
  connected: { icon: '✓', text: '연결됨' },
  offline: { icon: '!', text: '연결 안 됨' },
}
