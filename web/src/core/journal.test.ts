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

import {
  canReformat,
  groupTurns,
  isSafeUrl,
  orderNotes,
  sectionsOf,
  titleOf,
  type JournalDetail,
  type Note,
  type Turn,
} from './journal.ts'

function detail(overrides: Partial<JournalDetail> & { summary?: string[] } = {}): JournalDetail {
  const { summary = [], ...rest } = overrides
  return {
    session: item({ summary }),
    summary_cites: [],
    citations: [],
    checks: [],
    persona_name: '제니',
    notes: [],
    turns: [],
    ...rest,
  }
}

describe('sectionsOf', () => {
  it('새 형식은 첫 줄이 결론이고 나머지가 알게 된 것이다', () => {
    const sections = sectionsOf(
      detail({ summary: ['결론', '하나', '둘'], summary_cites: [[1], [], [2, 1]], checks: ['확인'] }),
    )
    expect(sections.conclusion).toEqual({ text: '결론', cites: [1] })
    expect(sections.findings).toEqual([
      { text: '하나', cites: [] },
      { text: '둘', cites: [2, 1] },
    ])
    expect(sections.checks).toEqual(['확인'])
    expect(sections.legacy).toBe(false)
  })

  it('checks가 null이면 예전 형식이라 요약 줄 목록이다', () => {
    const sections = sectionsOf(detail({ summary: ['가', '나'], checks: null }))
    expect(sections.conclusion).toBeNull()
    expect(sections.findings.map((l) => l.text)).toEqual(['가', '나'])
    expect(sections.legacy).toBe(true)
  })

  it('요약이 없으면 비어 있고 예전 형식도 아니다', () => {
    expect(sectionsOf(detail({ summary: [], checks: null })).legacy).toBe(false)
    expect(sectionsOf(detail({ summary: [] })).conclusion).toBeNull()
  })

  it('다시 정리는 끝나고 정리를 마친 예전 형식일 때만 된다', () => {
    expect(canReformat(detail({ summary: ['가'], checks: null }))).toBe(true)
    expect(canReformat(detail({ summary: ['가'], checks: [] }))).toBe(false)
    const pending = detail({ summary: ['가'], checks: null })
    pending.session.journal_status = 'pending'
    expect(canReformat(pending)).toBe(false)
    const active = detail({ summary: ['가'], checks: null })
    active.session.status = 'active'
    expect(canReformat(active)).toBe(false)
  })
})

function turn(id: string, role: Turn['role'], text: string, extra: Partial<Turn> = {}): Turn {
  return {
    id,
    seq: Number(id.replace(/\D/g, '')) || 0,
    role,
    text,
    interrupted: false,
    merged_from: null,
    created_at: 'x',
    attachments: [],
    ...extra,
  }
}

describe('groupTurns', () => {
  it('병합된 뒷말은 앞말과 한 말풍선이다', () => {
    const bubbles = groupTurns([
      turn('t0', 'assistant', '안녕하세요'),
      turn('t1', 'user', '앞말이에요'),
      turn('t2', 'user', '뒷말이에요', { merged_from: 't1' }),
      turn('t3', 'assistant', '답이에요'),
    ])
    expect(bubbles.map((b) => [b.role, b.texts])).toEqual([
      ['assistant', ['안녕하세요']],
      ['user', ['앞말이에요', '뒷말이에요']],
      ['assistant', ['답이에요']],
    ])
  })

  it('앞말을 찾지 못하거나 화자가 다르면 따로 둔다', () => {
    const bubbles = groupTurns([
      turn('t1', 'user', '가'),
      turn('t2', 'assistant', '나', { merged_from: 't1' }),
      turn('t3', 'user', '다', { merged_from: 't99' }),
    ])
    expect(bubbles).toHaveLength(3)
  })

  it('끊긴 답변 표시와 빈 턴 건너뛰기', () => {
    const bubbles = groupTurns([
      turn('t1', 'assistant', '말하다', { interrupted: true }),
      turn('t2', 'user', '   '),
    ])
    expect(bubbles).toHaveLength(1)
    expect(bubbles[0].interrupted).toBe(true)
  })
})

function note(id: string, kind: Note['kind'], extra: Partial<Note> = {}): Note {
  return { id, kind, content: id, starred: false, done: false, created_at: 'x', cites: [], ...extra }
}

describe('orderNotes', () => {
  it('별표가 먼저, 완료는 맨 뒤, 나머지는 만든 차례다', () => {
    const notes = [
      note('a', 'idea'),
      note('b', 'idea', { done: true, starred: true }),
      note('c', 'idea', { starred: true }),
      note('d', 'todo'),
      note('e', 'idea'),
    ]
    expect(orderNotes(notes, 'idea').map((n) => n.id)).toEqual(['c', 'a', 'e', 'b'])
    expect(orderNotes(notes, 'todo').map((n) => n.id)).toEqual(['d'])
    expect(orderNotes(notes, 'memo')).toEqual([])
  })
})

describe('그 밖의 도우미', () => {
  it('인용 주소는 http·https만 링크가 된다', () => {
    expect(isSafeUrl('https://example.com/a')).toBe(true)
    expect(isSafeUrl('javascript:alert(1)')).toBe(false)
    expect(isSafeUrl('//evil.example.com')).toBe(false)
  })

  it('제목은 공백을 한 칸으로 줄인다', () => {
    expect(titleOf('  가 \n  나\t다 ')).toBe('가 나 다')
    expect(titleOf('   ')).toBe('')
  })
})
