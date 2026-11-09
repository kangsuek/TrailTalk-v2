// 모달(확인 창·시트) 안에 포커스를 가두고, 닫히면 열었던 요소로 포커스를 돌려준다(접근성, M6).
// DOM을 더하지 않는 wrapper(display: contents)라 모달의 마크업·스타일은 그대로다. 열릴 때 이미 모달 안에
// 포커스가 있으면(autoFocus) 그대로 두고, 없으면 처음 초점 가능한 요소로 옮긴다. Escape는 각 모달이 맡는다.
import { useEffect, useRef, useState, type ReactNode } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',')

export default function FocusScope({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  // 열기 전에 포커스가 있던 요소. 자식의 autoFocus는 DOM에 반영될 때 포커스를 옮기므로 그 전인 첫 렌더에서
  // 기억해야 한다. 닫힐 때 돌려준다
  const [opener] = useState(() =>
    typeof document !== 'undefined' && document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  )

  useEffect(() => {
    const scope = ref.current
    if (scope && !scope.contains(document.activeElement)) {
      scope.querySelector<HTMLElement>(FOCUSABLE)?.focus()
    }
    return () => {
      if (opener && opener.isConnected && opener !== document.body) opener.focus()
    }
  }, [opener])

  function onKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Tab') return
    const items = [...(ref.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])]
    if (items.length === 0) return
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement
    if (event.shiftKey && (active === first || !ref.current?.contains(active))) {
      event.preventDefault()
      last.focus()
    } else if (!event.shiftKey && (active === last || !ref.current?.contains(active))) {
      event.preventDefault()
      first.focus()
    }
  }

  return (
    <div ref={ref} style={{ display: 'contents' }} onKeyDown={onKeyDown}>
      {children}
    </div>
  )
}
