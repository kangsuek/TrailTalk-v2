// 일지·노트 API(docs/client-contract.md 3절). 타입은 서버 OpenAPI에서 생성한 schema.d.ts를 쓴다.
import type { JournalItem } from '../core/journal.ts'
import { ApiError, request } from './http.ts'
import type { components } from './schema.d.ts'

export type JournalDetail = components['schemas']['JournalDetail']
export type NoteOut = components['schemas']['NoteOut']
export type TurnOut = components['schemas']['TurnOut']
export type OpenIdea = components['schemas']['OpenIdea']
export type NotePatch = components['schemas']['NotePatch']

// core의 JournalItem이 서버 스키마와 어긋나면(필드 추가·삭제) 여기서 타입 오류가 난다
type GeneratedItem = components['schemas']['JournalItem']
const _itemMatchesServer: (item: GeneratedItem) => JournalItem = (item) => item
void _itemMatchesServer

const BAD_RESPONSE = '서버 응답을 읽지 못했어요.'

async function json<T>(response: Response, check: (body: unknown) => boolean): Promise<T> {
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ApiError('bad_response', BAD_RESPONSE, response.status)
  }
  if (!check(body)) throw new ApiError('bad_response', BAD_RESPONSE, response.status)
  return body as T
}

const isObject = (body: unknown): boolean => typeof body === 'object' && body !== null

const path = (id: string) => `/api/journal/${encodeURIComponent(id)}`

/** 최근 30일 일지(진행 중 포함, 최신순). */
export async function listJournal(signal?: AbortSignal): Promise<JournalItem[]> {
  const response = await request('/api/journal', 'GET', undefined, signal)
  return json(response, Array.isArray)
}

export async function getJournal(id: string, signal?: AbortSignal): Promise<JournalDetail> {
  const response = await request(path(id), 'GET', undefined, signal)
  return json(response, isObject)
}

/** 제목을 고친다(서버가 공백을 줄이고 1~200자를 확인한다). 바뀐 일지 항목을 돌려준다. */
export async function renameJournal(id: string, title: string): Promise<JournalItem> {
  return json(await request(path(id), 'PATCH', { title }), isObject)
}

/** 대화를 지운다(전문·노트까지). 진행 중이면 409 session_active. */
export async function deleteJournal(id: string): Promise<void> {
  await request(path(id), 'DELETE')
}

/** 일지를 다시 정리한다(202). 돌려주는 항목의 journal_status가 pending이면 정리가 시작된 것이다. */
export async function retryJournal(id: string): Promise<JournalItem> {
  return json(await request(`${path(id)}/retry`, 'POST', {}), isObject)
}

export async function updateNote(id: string, patch: NotePatch): Promise<NoteOut> {
  return json(await request(`/api/notes/${encodeURIComponent(id)}`, 'PATCH', patch), isObject)
}

/** 시작 화면의 "지난 아이디어 이어 가기" 목록. */
export async function listOpenIdeas(limit = 5, signal?: AbortSignal): Promise<OpenIdea[]> {
  const response = await request(`/api/notes/open-ideas?limit=${limit}`, 'GET', undefined, signal)
  return json(response, Array.isArray)
}
