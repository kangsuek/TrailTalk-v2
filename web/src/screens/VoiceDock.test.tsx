import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ModeToggle from '../components/ModeToggle.tsx'
import VoiceDock from './VoiceDock.tsx'

afterEach(() => {
  cleanup()
  vi.useRealTimers()
})

describe('VoiceDock', () => {
  it.each([
    ['idle', '음성 대화 시작', '눌러서 시작해요'],
    ['listening', '듣는 중', '편하게 말씀하세요'],
    ['processing', /생각하는 중/, '누르면 멈추고 다시 들을게요'],
    ['speaking', /말하는 중/, '말하면 바로 멈추고 들어요'],
    ['paused', /쉬는 중/, '누르면 다시 들어요'],
  ] as const)('%s 상태의 큰 버튼 이름과 안내 문구', (state, name, hint) => {
    render(<VoiceDock state={state} onTap={() => {}} />)
    expect(screen.getByRole('button', { name })).toBeEnabled()
    expect(screen.getByText(hint)).toBeInTheDocument()
  })

  it('시작하는 중·정리 중에는 큰 버튼이 잠긴다', () => {
    const { rerender } = render(<VoiceDock state="starting" onTap={() => {}} />)
    expect(screen.getByRole('button', { name: '연결하는 중' })).toBeDisabled()
    rerender(<VoiceDock state="closing" onTap={() => {}} />)
    expect(screen.getByRole('button', { name: '정리하는 중' })).toBeDisabled()
  })

  it('한 번 누르면 tap, 대화종료 버튼은 onEnd이고 시작 화면에는 대화종료가 없다', async () => {
    const onTap = vi.fn()
    const onEnd = vi.fn()
    const { rerender } = render(<VoiceDock state="listening" onTap={onTap} onEnd={onEnd} />)
    await userEvent.click(screen.getByRole('button', { name: /듣는 중/ }))
    expect(onTap).toHaveBeenCalledTimes(1)
    await userEvent.click(screen.getByRole('button', { name: '대화종료' }))
    expect(onEnd).toHaveBeenCalledTimes(1)
    rerender(<VoiceDock state="idle" onTap={onTap} />)
    expect(screen.queryByRole('button', { name: '대화종료' })).toBeNull()
  })

  it('700ms 길게 누르면 onLongPress이고 그 뒤의 click은 tap으로 세지 않는다', () => {
    vi.useFakeTimers()
    const onTap = vi.fn()
    const onLongPress = vi.fn()
    render(<VoiceDock state="listening" onTap={onTap} onLongPress={onLongPress} />)
    const button = screen.getByRole('button', { name: /듣는 중/ })
    fireEvent.pointerDown(button, { button: 0 })
    act(() => void vi.advanceTimersByTime(699))
    expect(onLongPress).not.toHaveBeenCalled()
    act(() => void vi.advanceTimersByTime(2))
    expect(onLongPress).toHaveBeenCalledTimes(1)
    fireEvent.pointerUp(button)
    fireEvent.click(button) // 길게 누른 뒤에 따라오는 click
    expect(onTap).not.toHaveBeenCalled()
    fireEvent.click(button) // 다음 짧은 누르기는 tap이다
    expect(onTap).toHaveBeenCalledTimes(1)
  })

  it('짧게 누르다 떼면 길게 누르기로 판정하지 않는다', () => {
    vi.useFakeTimers()
    const onLongPress = vi.fn()
    render(<VoiceDock state="listening" onTap={() => {}} onLongPress={onLongPress} />)
    const button = screen.getByRole('button', { name: /듣는 중/ })
    fireEvent.pointerDown(button, { button: 0 })
    act(() => void vi.advanceTimersByTime(300))
    fireEvent.pointerUp(button)
    act(() => void vi.advanceTimersByTime(1000))
    expect(onLongPress).not.toHaveBeenCalled()
  })

  it('방식 선택 버튼을 자식으로 받아 큰 버튼 위에 둔다', () => {
    render(
      <VoiceDock state="idle" onTap={() => {}}>
        <ModeToggle mode="voice" onChange={() => {}} />
      </VoiceDock>,
    )
    expect(screen.getByRole('group', { name: '대화 방식' })).toBeInTheDocument()
  })
})

describe('ModeToggle', () => {
  it('고른 방식이 눌린 상태이고 다른 쪽을 누르면 바뀐다', async () => {
    const onChange = vi.fn()
    render(<ModeToggle mode="voice" onChange={onChange} />)
    expect(screen.getByRole('button', { name: '음성으로' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '글로' })).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(screen.getByRole('button', { name: '글로' }))
    expect(onChange).toHaveBeenCalledWith('text')
  })

  it('음성이 막혀 있으면 음성 쪽만 잠기고, disabled면 둘 다 잠긴다', () => {
    const { rerender } = render(<ModeToggle mode="text" onChange={() => {}} voiceDisabled />)
    expect(screen.getByRole('button', { name: '음성으로' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '글로' })).toBeEnabled()
    rerender(<ModeToggle mode="text" onChange={() => {}} disabled />)
    expect(screen.getByRole('button', { name: '글로' })).toBeDisabled()
  })
})
