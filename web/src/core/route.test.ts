import { describe, expect, it } from 'vitest'
import { parseRoute, pathOf, tabOf, type Route } from './route.ts'

describe('parseRoute', () => {
  it('화면 경로를 화면으로 바꾼다', () => {
    expect(parseRoute('/')).toEqual({ name: 'chat' })
    expect(parseRoute('/journal')).toEqual({ name: 'journal' })
    expect(parseRoute('/journal/abc-123')).toEqual({ name: 'journalDetail', id: 'abc-123' })
    expect(parseRoute('/settings')).toEqual({ name: 'settings' })
  })

  it('끝의 슬래시와 겹친 슬래시를 허용한다', () => {
    expect(parseRoute('/journal/')).toEqual({ name: 'journal' })
    expect(parseRoute('//journal//x//')).toEqual({ name: 'journalDetail', id: 'x' })
  })

  it('모르는 경로와 깨진 인코딩은 대화다', () => {
    expect(parseRoute('/nope')).toEqual({ name: 'chat' })
    expect(parseRoute('/journal/a/b')).toEqual({ name: 'chat' })
    expect(parseRoute('/settings/x')).toEqual({ name: 'chat' })
    expect(parseRoute('/journal/%E0%A4%A')).toEqual({ name: 'chat' })
  })
})

describe('pathOf', () => {
  it('parseRoute와 서로 되돌릴 수 있다', () => {
    const routes: Route[] = [
      { name: 'chat' },
      { name: 'journal' },
      { name: 'journalDetail', id: '가/나 다?#' },
      { name: 'settings' },
    ]
    for (const route of routes) expect(parseRoute(pathOf(route))).toEqual(route)
  })

  it('ID를 경로에 안전하게 넣는다', () => {
    expect(pathOf({ name: 'journalDetail', id: 'a/b' })).toBe('/journal/a%2Fb')
  })
})

describe('tabOf', () => {
  it('일지 상세는 일지 탭이다', () => {
    expect(tabOf({ name: 'journalDetail', id: 'x' })).toBe('journal')
    expect(tabOf({ name: 'journal' })).toBe('journal')
    expect(tabOf({ name: 'settings' })).toBe('settings')
    expect(tabOf({ name: 'chat' })).toBe('chat')
  })
})
