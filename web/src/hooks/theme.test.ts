import { afterEach, describe, expect, it } from 'vitest'
import { applyTheme, readTheme, rememberTheme } from './theme.ts'

afterEach(() => {
  localStorage.clear()
  delete document.documentElement.dataset.theme
})

describe('화면 모드', () => {
  it('기억한 값이 없거나 이상하면 시스템 설정을 따른다', () => {
    expect(readTheme()).toBe('system')
    localStorage.setItem('trailtalk.theme', 'sepia')
    expect(readTheme()).toBe('system')
  })

  it('고른 값을 기억하고 다시 읽는다', () => {
    rememberTheme('dark')
    expect(readTheme()).toBe('dark')
  })

  it('라이트·다크는 data-theme으로 고정하고 시스템이면 지운다', () => {
    applyTheme('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    applyTheme('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    applyTheme('system')
    expect(document.documentElement.dataset.theme).toBeUndefined()
  })
})
