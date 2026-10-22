import { describe, expect, it } from 'vitest'
import { CONNECTION_LABEL, HEALTH_INTERVAL_MS, nextConnection } from './connection.ts'

describe('connection', () => {
  it('판정은 health 결과를 그대로 따른다', () => {
    expect(nextConnection({ ok: true })).toBe('connected')
    expect(nextConnection({ ok: false })).toBe('offline')
  })

  it('확인 주기는 30초이고 모든 상태에 아이콘과 문구가 있다', () => {
    expect(HEALTH_INTERVAL_MS).toBe(30_000)
    for (const label of Object.values(CONNECTION_LABEL)) {
      expect(label.icon).toBeTruthy()
      expect(label.text).toBeTruthy()
    }
  })
})
