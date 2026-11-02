// Claude 구독 사용 한도(GET /api/usage, 계획서 S3-36). 응답 타입은 schema.d.ts(npm run gen:api).
import type { UsageLimits } from '../core/usage.ts'
import type { components } from './schema.d.ts'
import { request } from './http.ts'

type UsageResponse = components['schemas']['UsageOut']

export async function fetchUsage(signal?: AbortSignal): Promise<UsageLimits> {
  const response = await request('/api/usage', 'GET', undefined, signal)
  const body: UsageResponse = await response.json()
  return {
    status: body.status,
    five_hour: body.five_hour,
    seven_day: body.seven_day,
  }
}
