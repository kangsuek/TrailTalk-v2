// 음성 대화의 조작 영역(시안 대화 01~04): 큰 버튼과 대화종료 버튼, 상태 문구.
// 큰 버튼: 한 번 누르기 = 시작·끼어들기·쉬기 재개(tap), 길게 누르기 = 종료(long_press, 보조 수단).
// 일시 중단 버튼과 쉬는 중 화면(시안 대화 06)은 M4에서 더한다.
import { useRef, type PointerEvent, type ReactNode } from 'react'
import type { SessionStateName } from '../core/index.ts'

const LONG_PRESS_MS = 700

type DockState = SessionStateName | 'starting'

const COPY: Record<DockState, { aria: string; hint: string }> = {
  idle: { aria: '음성 대화 시작', hint: '눌러서 시작해요' },
  starting: { aria: '연결하는 중', hint: '연결하는 중…' },
  listening: { aria: '듣는 중. 길게 누르면 대화를 마쳐요', hint: '편하게 말씀하세요' },
  processing: { aria: '생각하는 중. 누르면 멈추고 다시 듣기', hint: '누르면 멈추고 다시 들을게요' },
  speaking: { aria: '말하는 중. 누르면 끼어들기', hint: '말하면 바로 멈추고 들어요' },
  paused: { aria: '쉬는 중. 누르면 다시 듣기', hint: '누르면 다시 들어요' },
  offline: { aria: '연결이 끊겼어요', hint: '연결이 끊겼어요' },
  closing: { aria: '정리하는 중', hint: '일지로 정리하는 중…' },
}

function Glyph({ state }: { state: DockState }) {
  if (state === 'processing') {
    return (
      <svg className="ic ic-glyph" viewBox="0 0 24 24" aria-hidden="true">
        <circle cx="6" cy="12" r="1.6" />
        <circle cx="12" cy="12" r="1.6" />
        <circle cx="18" cy="12" r="1.6" />
      </svg>
    )
  }
  if (state === 'speaking') {
    return (
      <svg className="ic ic-glyph" viewBox="0 0 24 24" aria-hidden="true">
        <path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 10v4" />
      </svg>
    )
  }
  return (
    <svg className="ic ic-glyph" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  )
}

export default function VoiceDock({
  state,
  onTap,
  onLongPress,
  onEnd,
  children,
}: {
  state: DockState
  onTap: () => void
  onLongPress?: () => void
  /** 대화종료 버튼(없으면 시작 화면이라 보이지 않는다) */
  onEnd?: () => void
  /** 큰 버튼 줄 위에 둘 것(방식 선택 버튼) */
  children?: ReactNode
}) {
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const longFired = useRef(false)
  const copy = COPY[state]
  const disabled = state === 'starting' || state === 'closing'

  const cancelTimer = () => {
    clearTimeout(timer.current)
    timer.current = undefined
  }
  // 포인터는 길게 누르기만 판정하고 한 번 누르기는 click으로 받는다(키보드·스크린리더도 click만 보낸다)
  const onPointerDown = (event: PointerEvent<HTMLButtonElement>) => {
    if (event.button !== 0 || !onLongPress) return
    longFired.current = false
    cancelTimer()
    timer.current = setTimeout(() => {
      timer.current = undefined
      longFired.current = true
      onLongPress()
    }, LONG_PRESS_MS)
  }
  const onClick = () => {
    if (longFired.current) {
      longFired.current = false // 길게 누른 뒤에 오는 click은 무시한다
      return
    }
    onTap()
  }

  return (
    <div className="dock voice-dock" data-state={state}>
      {children}
      {state === 'listening' && (
        <p className="voice-note">말이 끊기면 자동으로 보내요</p>
      )}
      <div className="voice-row">
        <span aria-hidden="true" />
        <button
          type="button"
          className="voice-button"
          aria-label={copy.aria}
          disabled={disabled}
          onClick={onClick}
          onPointerDown={onPointerDown}
          onPointerUp={cancelTimer}
          onPointerLeave={cancelTimer}
          onPointerCancel={cancelTimer}
          onContextMenu={(event) => event.preventDefault()} // 휴대폰 길게 누르기 메뉴를 막는다
        >
          <Glyph state={state} />
        </button>
        {onEnd ? (
          <div className="side-btn">
            <button type="button" aria-label="대화종료" onClick={onEnd}>
              <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
                <rect x="6" y="6" width="12" height="12" rx="2" />
              </svg>
            </button>
            <span aria-hidden="true">대화종료</span>
          </div>
        ) : (
          <span aria-hidden="true" />
        )}
      </div>
      <p className="voice-hint" role="status">
        {copy.hint}
      </p>
    </div>
  )
}
