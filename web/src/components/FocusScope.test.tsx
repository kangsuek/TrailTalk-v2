import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
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

  it('열었던 요소가 사라졌으면 포커스를 억지로 옮기지 않는다', async () => {
    const { rerender } = render(<Host />)
    await userEvent.click(screen.getByRole('button', { name: '열기' }))
    rerender(<div />) // 열었던 버튼과 모달이 모두 사라진다
    expect(document.body).toHaveFocus()
  })
})
