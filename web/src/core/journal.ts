// 일지 목록·상세 화면의 순수 로직(docs/client-contract.md 3절): 날짜 묶음, 카드 종류, 표시 문구.
// 서버 응답 모양은 여기에 적고, 생성 타입(schema.d.ts)과 같은지는 api/journal.ts가 타입으로 확인한다.
import { plainText } from './markdown.ts'

export interface NoteCounts {
  idea: number
  todo: number
  memo: number
}

export type JournalStatus = 'pending' | 'done' | 'failed' | null

export interface JournalItem {
  id: string
  date: string
  started_at: string
  ended_at: string | null
  status: 'active' | 'paused' | 'ended'
  title: string | null
  summary: string[]
  tags: string[]
  journal_status: JournalStatus
  counts: NoteCounts
}

export const TITLE_FALLBACK = '제목 없는 대화'
/** 정리 중인 일지를 다시 불러오는 간격과 최대 시간(client-contract 3.2) */
export const PENDING_POLL_MS = 3000
export const PENDING_POLL_MAX_MS = 120_000

const WEEKDAYS = '일월화수목금토'

/** 'YYYY-MM-DD' → '10월 22일 (목)'. 시간대 계산 없이 서버가 준 날짜를 그대로 쓴다. */
export function dateLabel(date: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date)
  if (!match) return date
  const [, year, month, day] = match.map(Number)
  const weekday = WEEKDAYS[new Date(year, month - 1, day).getDay()]
  return `${month}월 ${day}일 (${weekday})`
}

/** 기기 시각으로 '오전 9:05'. */
export function timeLabel(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  const hours = at.getHours()
  const hour12 = hours % 12 || 12
  const minutes = String(at.getMinutes()).padStart(2, '0')
  return `${hours < 12 ? '오전' : '오후'} ${hour12}:${minutes}`
}

/** 끝난 대화의 길이('38분', 1분보다 짧으면 '1분 미만'). 끝나지 않았으면 null. */
export function durationLabel(startedAt: string, endedAt: string | null): string | null {
  if (!endedAt) return null
  const ms = new Date(endedAt).getTime() - new Date(startedAt).getTime()
  if (Number.isNaN(ms)) return null
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return '1분 미만'
  if (minutes < 60) return `${minutes}분`
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  return rest ? `${hours}시간 ${rest}분` : `${hours}시간`
}

/** '오전 7:12 · 38분'. 진행 중이면 길이 대신 상태. */
export function metaLine(item: Pick<JournalItem, 'started_at' | 'ended_at' | 'status'>): string {
  const time = timeLabel(item.started_at)
  const tail =
    item.status === 'active'
      ? '진행 중'
      : item.status === 'paused'
        ? '쉬는 중'
        : durationLabel(item.started_at, item.ended_at)
  return [time, tail].filter(Boolean).join(' · ')
}

export interface DateGroup {
  date: string
  label: string
  items: JournalItem[]
}

/** 서버가 준 최신순을 `date`로 묶는다(순서는 그대로). */
export function groupByDate(items: readonly JournalItem[]): DateGroup[] {
  const groups: DateGroup[] = []
  for (const item of items) {
    const last = groups.at(-1)
    if (last && last.date === item.date) last.items.push(item)
    else groups.push({ date: item.date, label: dateLabel(item.date), items: [item] })
  }
  return groups
}

export type CardKind = 'active' | 'pending' | 'failed' | 'unorganized' | 'done'

/** 카드 모양을 정하는 상태. 끝나지 않은 대화가 가장 먼저다. */
export function cardKind(item: Pick<JournalItem, 'status' | 'journal_status'>): CardKind {
  if (item.status !== 'ended') return 'active'
  switch (item.journal_status) {
    case 'pending':
      return 'pending'
    case 'failed':
      return 'failed'
    case null:
      return 'unorganized'
    default:
      return 'done'
  }
}

export const KIND_LABEL = { idea: '아이디어', todo: '할 일', memo: '메모' } as const

/** 0이 아닌 종류만 '아이디어 3' 꼴로. */
export function countPills(
  counts: NoteCounts,
): { kind: keyof NoteCounts; text: string }[] {
  return (['idea', 'todo', 'memo'] as const)
    .filter((kind) => counts[kind] > 0)
    .map((kind) => ({ kind, text: `${KIND_LABEL[kind]} ${counts[kind]}` }))
}

/** 목록 카드의 요약 한 줄(서식 표시를 뺀 첫 줄). */
export function previewOf(item: Pick<JournalItem, 'summary'>): string | null {
  const line = item.summary.map((text) => plainText(text).trim()).find(Boolean)
  return line ?? null
}

export const hasPending = (items: readonly JournalItem[]): boolean =>
  items.some((item) => item.journal_status === 'pending')

/** 진행 중(active)인 대화는 지울 수 없다. 쉬는 중·정리 중은 지운다(정리를 멈춘다, 규약 3.2). */
export const isDeletable = (item: Pick<JournalItem, 'status'>): boolean => item.status !== 'active'

// --- 일지 상세(client-contract 3.2) ---

export interface Attachment {
  id: string
  name: string
  mime: string
  size: number
  thumb: boolean
}

export interface Turn {
  id: string
  seq: number
  role: 'user' | 'assistant'
  text: string
  interrupted: boolean
  merged_from: string | null
  created_at: string
  attachments: Attachment[]
}

export interface Note {
  id: string
  kind: 'idea' | 'todo' | 'memo'
  content: string
  starred: boolean
  done: boolean
  created_at: string
  cites: number[]
}

export interface Citation {
  n: number
  title: string
  url: string
}

export interface JournalDetail {
  session: JournalItem
  summary_cites: number[][]
  citations: Citation[]
  checks: string[] | null
  persona_name: string
  notes: Note[]
  turns: Turn[]
}

export interface CitedLine {
  text: string
  cites: number[]
}

export interface Sections {
  /** 새 형식이면 요약 첫 줄(굵게) */
  conclusion: CitedLine | null
  /** 새 형식의 "알게 된 것" 또는 예전 형식의 요약 줄 */
  findings: CitedLine[]
  /** 새 형식의 "확인할 것" */
  checks: string[]
  /** 예전 형식(checks가 null인 요약)이다. 끝난 대화면 다시 정리해 새 형식으로 바꿀 수 있다 */
  legacy: boolean
}

/** 요약 줄을 결론·알게 된 것으로 나눈다(규약 3.2 "표시 형식"). */
export function sectionsOf(detail: Pick<JournalDetail, 'session' | 'summary_cites' | 'checks'>): Sections {
  const lines: CitedLine[] = detail.session.summary.map((text, i) => ({
    text,
    cites: detail.summary_cites[i] ?? [],
  }))
  if (detail.checks === null) {
    return { conclusion: null, findings: lines, checks: [], legacy: lines.length > 0 }
  }
  return { conclusion: lines[0] ?? null, findings: lines.slice(1), checks: detail.checks, legacy: false }
}

/** 예전 형식으로 정리가 끝난 일지만 다시 정리로 새 형식이 된다. */
export const canReformat = (detail: Pick<JournalDetail, 'session' | 'summary_cites' | 'checks'>): boolean =>
  detail.session.status === 'ended' &&
  detail.session.journal_status === 'done' &&
  sectionsOf(detail).legacy

export interface TranscriptBubble {
  id: string
  role: 'user' | 'assistant'
  /** 병합된 뒷말은 같은 말풍선 안의 다음 조각이다 */
  texts: string[]
  interrupted: boolean
  attachments: Attachment[]
  turnIds: string[]
}

/** 전문을 말풍선으로. `merged_from`이 가리키는 앞말과 같은 화자의 뒷말은 한 말풍선으로 합친다. */
export function groupTurns(turns: readonly Turn[]): TranscriptBubble[] {
  const bubbles: TranscriptBubble[] = []
  for (const turn of turns) {
    if (!turn.text.trim() && turn.attachments.length === 0) continue
    const target =
      turn.merged_from === null
        ? undefined
        : bubbles.findLast((b) => b.role === turn.role && b.turnIds.includes(turn.merged_from!))
    if (target) {
      if (turn.text.trim()) target.texts.push(turn.text)
      target.attachments.push(...turn.attachments)
      target.turnIds.push(turn.id)
      target.interrupted = turn.interrupted
    } else {
      bubbles.push({
        id: turn.id,
        role: turn.role,
        texts: turn.text.trim() ? [turn.text] : [],
        interrupted: turn.interrupted,
        attachments: [...turn.attachments],
        turnIds: [turn.id],
      })
    }
  }
  return bubbles
}

/** 한 종류의 노트를 보일 차례로. 안 끝난 것이 먼저, 그 안에서 별표가 먼저, 나머지는 만든 차례다. */
export function orderNotes(notes: readonly Note[], kind: Note['kind']): Note[] {
  const rank = (note: Note) => (note.done ? 2 : 0) + (note.starred ? 0 : 1)
  return notes
    .map((note, index) => ({ note, index }))
    .filter(({ note }) => note.kind === kind)
    .sort((a, b) => rank(a.note) - rank(b.note) || a.index - b.index)
    .map(({ note }) => note)
}

/** 인용 주소가 링크가 될 수 있는지(http·https만, 규약 3.2). */
export const isSafeUrl = (url: string): boolean => /^https?:\/\/[^\s<>"]+$/i.test(url)

/** 제목 수정 입력의 길이(서버는 공백을 줄인 뒤 1~200자를 본다). */
export const TITLE_MAX = 200
export const titleOf = (input: string): string => input.split(/\s+/).filter(Boolean).join(' ')

/** 기기 시각으로 '10월 22일'. */
export function monthDayLabel(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return ''
  return `${at.getMonth() + 1}월 ${at.getDate()}일`
}
