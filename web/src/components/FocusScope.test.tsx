import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { StrictMode, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FocusScope from './FocusScope.tsx'

afterEach(cleanup)

function Host({ autoFocusCancel = true }: { autoFocusCancel?: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <div>
      <button onClick={() => setOpen(true)}>열기</button>
      <button>바깥 버튼</button>
      {open && (
        <FocusScope>
          <div role="alertdialog" aria-label="확인">
            <button onClick={() => setOpen(false)}>끝내기</button>
            <button autoFocus={autoFocusCancel} onClick={() => setOpen(false)}>
              계속하기
            </button>
          </div>
        </FocusScope>
      )}
    </div>
  )
}

describe('FocusScope', () => {
  it('Tab이 모달 안에서만 돈다(끝에서 처음으로, 처음에서 Shift+Tab하면 끝으로)', async () => {
    render(<Host />)
    await userEvent.click(screen.getByRole('button', { name: '열기' }))
    const first = screen.getByRole('button', { name: '끝내기' })
    const last = screen.getByRole('button', { name: '계속하기' })
    expect(last).toHaveFocus() // autoFocus를 존중한다
    await userEvent.tab()
    expect(first).toHaveFocus() // 바깥 버튼이 아니라 처음으로
    await userEvent.tab({ shift: true })
    expect(last).toHaveFocus() // 처음에서 거꾸로 가면 끝으로
    for (let i = 0; i < 5; i += 1) {
      await userEvent.tab()
      expect(screen.getByRole('button', { name: '바깥 버튼' })).not.toHaveFocus()
    }
  })

  it('autoFocus가 없으면 처음 초점 가능한 요소로 간다', async () => {
    render(<Host autoFocusCancel={false} />)
    await userEvent.click(screen.getByRole('button', { name: '열기' }))
    expect(screen.getByRole('button', { name: '끝내기' })).toHaveFocus()
  })

  it('닫으면 열었던 버튼으로 포커스가 돌아온다', async () => {
    render(<Host />)
    const opener = screen.getByRole('button', { name: '열기' })
    await userEvent.click(opener)
    await userEvent.click(screen.getByRole('button', { name: '계속하기' }))
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
    expect(opener).toHaveFocus()
  })

  it('배경을 눌러 포커스가 밖으로 나가도 다시 모달 안으로 돌아온다', async () => {
    render(<Host />)
    await userEvent.click(screen.getByRole('button', { name: '열기' }))
    screen.getByRole('button', { name: '바깥 버튼' }).focus() // 모달 밖으로 나갔다
    expect(screen.getByRole('button', { name: '끝내기' })).toHaveFocus()
  })

  it('숨은 입력(type=hidden)·tabindex=-1 요소는 Tab 순서에서 빠진다', async () => {
    render(
      <div>
        <button>바깥</button>
        <FocusScope>
          <div role="dialog" aria-label="폼">
            <button>처음</button>
            <button tabIndex={-1}>건너뜀</button>
            <button autoFocus>마지막</button>
            <input type="hidden" defaultValue="x" />
          </div>
        </FocusScope>
      </div>,
    )
    expect(screen.getByRole('button', { name: '마지막' })).toHaveFocus()
    await userEvent.tab() // 마지막에서 한 칸 더 가면 처음으로(숨은 입력이 끝으로 잡히지 않는다)
    expect(screen.getByRole('button', { name: '처음' })).toHaveFocus()
  })

  it('StrictMode(개발 서버)에서도 autoFocus한 안전 버튼에 포커스가 남는다', async () => {
    render(
      <StrictMode>
        <Host />
      </StrictMode>,
    )
    await userEvent.click(screen.getByRole('button', { name: '열기' }))
    expect(screen.getByRole('button', { name: '계속하기' })).toHaveFocus()
  })

  it('CSS로 숨긴(display:none·visibility:hidden) 요소는 Tab 순서에서 빠진다', async () => {
    render(
      <FocusScope>
        <div role="dialog" aria-label="폼">
          <button autoFocus>처음</button>
          <button>마지막</button>
          <button style={{ display: 'none' }}>숨김1</button>
          <button style={{ visibility: 'hidden' }}>숨김2</button>
        </div>
      </FocusScope>,
    )
    await userEvent.tab()
    expect(screen.getByRole('button', { name: '마지막' })).toHaveFocus()
    await userEvent.tab() // 숨은 버튼이 끝으로 잡히면 여기서 새 버린다
    expect(screen.getByRole('button', { name: '처음' })).toHaveFocus()
  })

  it('모달 둘이 동시에 마운트돼도 포커스 되돌림이 서로 싸우지 않고 맨 위 모달이 맡는다', async () => {
    render(
      <div>
        <button>바깥</button>
        <FocusScope>
          <div role="dialog" aria-label="아래">
            <button>아래 버튼</button>
          </div>
        </FocusScope>
        <FocusScope>
          <div role="dialog" aria-label="위">
            <button>위 버튼</button>
          </div>
        </FocusScope>
      </div>,
    )
    const calls = vi.spyOn(HTMLElement.prototype, 'focus')
    screen.getByRole('button', { name: '바깥' }).focus() // 둘 다의 바깥
    expect(screen.getByRole('button', { name: '위 버튼' })).toHaveFocus()
    expect(calls.mock.calls.length).toBeLessThan(10) // 무한 루프가 아니다
    calls.mockRestore()
  })

  it('포커스를 되돌릴 때 페이지를 스크롤하지 않는다', async () => {
    render(<Host />)
    await userEvent.click(screen.getByRole('button', { name: '열기' }))
    const calls = vi.spyOn(HTMLElement.prototype, 'focus')
    screen.getByRole('button', { name: '바깥 버튼' }).focus()
    const forced = calls.mock.calls.slice(1) // 첫 호출은 이 시험이 한 것
    expect(forced.length).toBeGreaterThan(0)
    for (const args of forced) expect(args[0]).toEqual({ preventScroll: true })
    calls.mockRestore()
  })

  it('열었던 요소가 사라졌으면 포커스를 억지로 옮기지 않는다', async () => {
    const { rerender } = render(<Host />)
    await userEvent.click(screen.getByRole('button', { name: '열기' }))
    rerender(<div />) // 열었던 버튼과 모달이 모두 사라진다
    expect(document.body).toHaveFocus()
  })
})
