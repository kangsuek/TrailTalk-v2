import { act, cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App.tsx'

function setPath(path: string) {
  window.history.replaceState(null, '', path)
}

beforeEach(() => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => Response.json({ status: 'ok', db: 'ok' })),
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  setPath('/')
})

describe('App 화면 경로', () => {
  it('경로가 연 화면을 보인다(새로고침)', () => {
    setPath('/journal/abc-123')
    render(<App />)
    expect(screen.getByRole('button', { name: '일지' })).toHaveAttribute('aria-current', 'page')
    expect(window.location.pathname).toBe('/journal/abc-123')
  })

  it('설정 경로는 설정 탭이다', () => {
    setPath('/settings')
    render(<App />)
    expect(screen.getByRole('button', { name: '설정' })).toHaveAttribute('aria-current', 'page')
  })

  it('모르는 경로와 끝 슬래시는 정규 경로로 바뀐다', () => {
    setPath('/nope/x')
    const first = render(<App />)
    expect(screen.getByRole('button', { name: '대화' })).toHaveAttribute('aria-current', 'page')
    expect(window.location.pathname).toBe('/')
    first.unmount()
    setPath('/journal/')
    render(<App />)
    expect(window.location.pathname).toBe('/journal')
  })

  it('탭을 누르면 주소가 바뀌고 뒤로 가기가 이전 화면으로 돌아간다', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '일지' }))
    expect(window.location.pathname).toBe('/journal')
    await userEvent.click(screen.getByRole('button', { name: '설정' }))
    expect(window.location.pathname).toBe('/settings')

    act(() => window.history.back())
    await vi.waitFor(() => expect(window.location.pathname).toBe('/journal'))
    expect(screen.getByRole('button', { name: '일지' })).toHaveAttribute('aria-current', 'page')
    act(() => window.history.back())
    await vi.waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(screen.getByRole('button', { name: '대화' })).toHaveAttribute('aria-current', 'page')
  })

  it('같은 탭을 다시 눌러도 기록을 쌓지 않는다', async () => {
    render(<App />)
    await userEvent.click(screen.getByRole('button', { name: '일지' }))
    const length = window.history.length
    await userEvent.click(screen.getByRole('button', { name: '일지' }))
    expect(window.history.length).toBe(length)
  })
})
