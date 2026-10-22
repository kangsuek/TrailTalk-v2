import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App.tsx'

function mockHealth(response: () => Promise<Response>) {
  vi.stubGlobal('fetch', vi.fn(response))
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('서버가 정상이면 연결됨을 보인다', async () => {
    mockHealth(async () => Response.json({ status: 'ok', db: 'ok' }))
    render(<App />)
    expect(await screen.findByText('연결됨')).toBeInTheDocument()
  })

  it('서버에 닿지 않으면 연결 안 됨을 보인다', async () => {
    mockHealth(async () => {
      throw new TypeError('network')
    })
    render(<App />)
    expect(await screen.findByText('연결 안 됨')).toBeInTheDocument()
  })

  it('DB 오류(503)도 연결 안 됨이다', async () => {
    mockHealth(async () => Response.json({ error: { code: 'db_unavailable' } }, { status: 503 }))
    render(<App />)
    expect(await screen.findByText('연결 안 됨')).toBeInTheDocument()
  })

  it('하단 탭 세 개가 있고 눌러서 바꾼다', async () => {
    mockHealth(async () => Response.json({ status: 'ok', db: 'ok' }))
    render(<App />)
    const nav = screen.getByRole('navigation', { name: '메인 메뉴' })
    expect(nav.querySelectorAll('button')).toHaveLength(3)
    expect(screen.getByRole('button', { name: '대화' })).toHaveAttribute('aria-current', 'page')
    await userEvent.click(screen.getByRole('button', { name: '일지' }))
    expect(screen.getByRole('button', { name: '일지' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('button', { name: '대화' })).not.toHaveAttribute('aria-current')
  })
})
