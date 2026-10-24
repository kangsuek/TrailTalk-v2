import { resolve } from 'node:path'
import { DatabaseSync } from 'node:sqlite'

// 격리 서버가 쓰는 임시 DB(web/.e2e/data)를 읽기 전용으로 열어 서버 기록을 직접 확인한다.
const DB_PATH = resolve(import.meta.dirname, '../.e2e/data/trailtalk.db')

export interface TurnRow {
  seq: number
  role: 'user' | 'assistant'
  text: string
  interrupted: number
  greeting: number
}

export interface SessionRow {
  id: string
  status: string
  ended_at: string | null
}

function query<T>(sql: string, ...params: string[]): T[] {
  // 서버가 쓰는 중이어도 잠금이 풀릴 때까지 잠깐 기다린다
  const db = new DatabaseSync(DB_PATH, { readOnly: true, timeout: 5_000 })
  try {
    return db.prepare(sql).all(...params) as T[]
  } finally {
    db.close()
  }
}

/** 가장 최근에 시작한 세션 */
export function latestSession(): SessionRow {
  const [row] = query<SessionRow>(
    'SELECT id, status, ended_at FROM conversation_session ORDER BY started_at DESC LIMIT 1',
  )
  if (!row) throw new Error('세션이 없습니다')
  return row
}

export function turnsOf(sessionId: string): TurnRow[] {
  return query<TurnRow>(
    'SELECT seq, role, text, interrupted, greeting FROM turn WHERE session_id = ? ORDER BY seq',
    sessionId,
  )
}
