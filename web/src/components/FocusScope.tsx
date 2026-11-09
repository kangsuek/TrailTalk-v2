// 모달(확인 창·시트) 안에 포커스를 가두고, 닫히면 열었던 요소로 포커스를 돌려준다(접근성, M6).
// DOM을 더하지 않는 wrapper(display: contents)라 모달의 마크업·스타일은 그대로다. 열릴 때 이미 모달 안에
// 포커스가 있으면(autoFocus) 그대로 두고, 없으면 처음 초점 가능한 요소로 옮긴다. 배경을 눌러 포커스가 밖으로
// 나가도 다시 안으로 돌려보낸다. Escape는 각 모달이 맡는다.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]',
].join(',')

/** Tab으로 닿는 요소(tabindex=-1·숨김 제외) */
function focusablesIn(root: HTMLElement | null): HTMLElement[] {
  if (!root) return []
  return [...root.querySelectorAll<HTMLElement>(FOCUSABLE)].filter(
    (element) => element.tabIndex >= 0 && !element.closest('[hidden]'),
  )
}

export default function FocusScope({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  // 열기 전에 포커스가 있던 요소. 자식의 autoFocus는 DOM에 반영될 때 포커스를 옮기므로 그 전인 첫 렌더에서
  // 기억해야 한다. 닫힐 때 돌려준다
  const [opener] = useState(() =>
    typeof document !== 'undefined' && document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  )
  // 모달 안에서 처음 포커스를 받은 요소(autoFocus). 개발 서버(StrictMode)는 효과를 두 번 돌려 정리 단계가
  // 포커스를 돌려놓으므로, 다시 열릴 때 이 요소로 되돌린다
  const initial = useRef<HTMLElement | null>(null)

  useEffect(() => {
    const scope = ref.current
    const active = document.activeElement
    if (scope?.contains(active)) {
      initial.current = active as HTMLElement
    } else if (initial.current?.isConnected) {
      initial.current.focus()
    } else {
      focusablesIn(scope)[0]?.focus()
    }
    // 배경을 눌러 포커스가 모달 밖으로 나가면 안으로 돌려보낸다
    const onFocusIn = (event: FocusEvent) => {
      if (scope && event.target instanceof Node && !scope.contains(event.target)) {
        focusablesIn(scope)[0]?.focus()
      }
    }
    document.addEventListener('focusin', onFocusIn)
    return () => {
      document.removeEventListener('focusin', onFocusIn)
      if (opener && opener.isConnected && opener !== document.body) opener.focus()
    }
  }, [opener])

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key !== 'Tab') return
    const items = focusablesIn(ref.current)
    if (items.length === 0) {
      event.preventDefault() // 초점 요소가 없는 모달에서 Tab이 뒤 페이지로 새지 않게
      return
    }
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
