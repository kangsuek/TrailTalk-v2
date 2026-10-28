import { describe, expect, it } from 'vitest'
import {
  cardKind,
  countPills,
  dateLabel,
  durationLabel,
  groupByDate,
  hasPending,
  isDeletable,
  metaLine,
  previewOf,
  timeLabel,
  type JournalItem,
} from './journal.ts'

function item(overrides: Partial<JournalItem> = {}): JournalItem {
  return {
    id: 'a',
    date: '2026-10-22',
    started_at: new Date(2026, 9, 22, 7, 12).toISOString(),
    ended_at: new Date(2026, 9, 22, 7, 50).toISOString(),
    status: 'ended',
    title: '제목',
    summary: [],
    tags: [],
    journal_status: 'done',
    counts: { idea: 0, todo: 0, memo: 0 },
    ...overrides,
  }
}

describe('표시 문구', () => {
  it('날짜를 요일과 함께 보인다', () => {
    expect(dateLabel('2026-10-22')).toBe('10월 22일 (목)')
    expect(dateLabel('2026-01-01')).toBe('1월 1일 (목)')
    expect(dateLabel('이상한 값')).toBe('이상한 값')
  })

  it('시각을 오전·오후 12시간제로 보인다', () => {
    expect(timeLabel(new Date(2026, 9, 22, 9, 5).toISOString())).toBe('오전 9:05')
    expect(timeLabel(new Date(2026, 9, 22, 0, 7).toISOString())).toBe('오전 12:07')
    expect(timeLabel(new Date(2026, 9, 22, 12, 0).toISOString())).toBe('오후 12:00')
    expect(timeLabel(new Date(2026, 9, 22, 23, 59).toISOString())).toBe('오후 11:59')
    expect(timeLabel('아님')).toBe('')
  })

  it('대화 길이를 분·시간으로 보인다', () => {
    const start = new Date(2026, 9, 22, 7, 0).toISOString()
    const at = (minutes: number, seconds = 0) =>
      new Date(2026, 9, 22, 7, minutes, seconds).toISOString()
    expect(durationLabel(start, at(38))).toBe('38분')
    expect(durationLabel(start, at(0, 20))).toBe('1분 미만')
    expect(durationLabel(start, new Date(2026, 9, 22, 9, 0).toISOString())).toBe('2시간')
    expect(durationLabel(start, new Date(2026, 9, 22, 8, 5).toISOString())).toBe('1시간 5분')
    expect(durationLabel(start, null)).toBeNull()
  })

  it('메타 줄은 시각과 길이(진행 중이면 상태)다', () => {
    expect(metaLine(item())).toBe('오전 7:12 · 38분')
    expect(metaLine(item({ status: 'active', ended_at: null }))).toBe('오전 7:12 · 진행 중')
    expect(metaLine(item({ status: 'paused', ended_at: null }))).toBe('오전 7:12 · 쉬는 중')
  })

  it('노트 개수 알약은 0이 아닌 종류만 보인다', () => {
    expect(countPills({ idea: 3, todo: 0, memo: 1 })).toEqual([
      { kind: 'idea', text: '아이디어 3' },
      { kind: 'memo', text: '메모 1' },
    ])
    expect(countPills({ idea: 0, todo: 0, memo: 0 })).toEqual([])
  })

  it('요약 미리보기는 서식을 뺀 첫 줄이다', () => {
    expect(previewOf({ summary: ['**결론**이다. [문서](https://a.com)', '둘째'] })).toBe(
      '결론이다. 문서',
    )
    expect(previewOf({ summary: ['  ', '둘째 줄'] })).toBe('둘째 줄')
    expect(previewOf({ summary: [] })).toBeNull()
  })
})

describe('목록 구성', () => {
  it('서버 순서를 지키며 date로 묶는다', () => {
    const groups = groupByDate([
      item({ id: '1', date: '2026-10-22' }),
      item({ id: '2', date: '2026-10-22' }),
      item({ id: '3', date: '2026-10-21' }),
    ])
    expect(groups.map((g) => [g.label, g.items.map((i) => i.id)])).toEqual([
      ['10월 22일 (목)', ['1', '2']],
      ['10월 21일 (수)', ['3']],
    ])
    expect(groupByDate([])).toEqual([])
  })

  it('카드 종류는 끝나지 않은 대화가 먼저다', () => {
    expect(cardKind({ status: 'active', journal_status: null })).toBe('active')
    expect(cardKind({ status: 'paused', journal_status: null })).toBe('active')
    expect(cardKind({ status: 'ended', journal_status: 'pending' })).toBe('pending')
    expect(cardKind({ status: 'ended', journal_status: 'failed' })).toBe('failed')
    expect(cardKind({ status: 'ended', journal_status: null })).toBe('unorganized')
    expect(cardKind({ status: 'ended', journal_status: 'done' })).toBe('done')
  })

  it('정리 중인 일지가 있는지 본다', () => {
    expect(hasPending([item(), item({ journal_status: 'pending' })])).toBe(true)
    expect(hasPending([item(), item({ journal_status: 'failed' })])).toBe(false)
  })

  it('진행 중인 대화만 지울 수 없다', () => {
    expect(isDeletable({ status: 'active' })).toBe(false)
    expect(isDeletable({ status: 'paused' })).toBe(true)
    expect(isDeletable({ status: 'ended' })).toBe(true)
  })
})
