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

  it('하단 메뉴는 현재 탭만 탭 순서에 있고, 화살표 키로 포커스만 옮기며 Enter로 이동한다', async () => {
    window.history.replaceState(null, '', '/') // 앞선 시험이 이동해 둔 주소를 처음으로
    mockHealth(async () => Response.json({ status: 'ok', db: 'ok' }))
    render(<App />)
    const tab = (name: string) => screen.getByRole('button', { name })
    expect(tab('대화')).toHaveAttribute('tabindex', '0')
    expect(tab('일지')).toHaveAttribute('tabindex', '-1')
    expect(tab('설정')).toHaveAttribute('tabindex', '-1')

    tab('대화').focus()
    await userEvent.keyboard('{ArrowRight}')
    expect(tab('일지')).toHaveFocus()
    expect(tab('대화')).toHaveAttribute('aria-current', 'page') // 옮기기만 했지 이동하지 않았다
    await userEvent.keyboard('{Enter}')
    expect(tab('일지')).toHaveAttribute('aria-current', 'page')
    expect(tab('일지')).toHaveAttribute('tabindex', '0')

    await userEvent.keyboard('{End}')
    expect(tab('설정')).toHaveFocus()
    await userEvent.keyboard('{ArrowRight}') // 끝에서 한 칸 더 가면 처음으로 돈다
    expect(tab('대화')).toHaveFocus()
    await userEvent.keyboard('{ArrowLeft}') // 처음에서 거꾸로 가면 끝으로 돈다
    expect(tab('설정')).toHaveFocus()
  })
})
