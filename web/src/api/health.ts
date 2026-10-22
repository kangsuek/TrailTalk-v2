import type { components } from './schema.d.ts'
import type { HealthResult } from '../core/connection.ts'

type Health = components['schemas']['HealthResponse']

/** GET /api/health. 서버가 응답하고 DB가 정상이면 ok. 닿지 않거나 503이면 ok가 아니다. */
/** 응답 없이 매달리면 이 시간 뒤 닿지 않은 것으로 본다. */
export const HEALTH_TIMEOUT_MS = 5_000

export async function fetchHealth(signal?: AbortSignal): Promise<HealthResult> {
  try {
    const timeout = AbortSignal.timeout(HEALTH_TIMEOUT_MS)
    const response = await fetch('/api/health', {
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
    })
    if (!response.ok) return { ok: false }
    const body = (await response.json()) as Health
    return { ok: body.status === 'ok' && body.db === 'ok' }
  } catch {
    return { ok: false }
  }
}
