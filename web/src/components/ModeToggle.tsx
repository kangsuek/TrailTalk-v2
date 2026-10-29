// "음성으로 / 글로" 선택 버튼(시안 대화 01·02·09). 시작 화면과 대화 화면에서 같은 위치·모양이다.
import type { InputMode } from '../hooks/inputMode.ts'

function MicIcon() {
  return (
    <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="9" y="3" width="6" height="11" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
    </svg>
  )
}

function KeyboardIcon() {
  return (
    <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
      <rect x="3" y="6" width="18" height="12" rx="2" />
      <path d="M7 10h.01M11 10h.01M15 10h.01M7 14h10" />
    </svg>
  )
}

export default function ModeToggle({
  mode,
  onChange,
  voiceDisabled = false,
  disabled = false,
}: {
  mode: InputMode
  onChange: (mode: InputMode) => void
  /** 음성 모듈을 아직 불러오지 못했거나 못 불러왔다 */
  voiceDisabled?: boolean
  /** 시작하는 중 등 바꿀 수 없다 */
  disabled?: boolean
}) {
  return (
    <div className="mode-toggle" role="group" aria-label="대화 방식">
      <button
        type="button"
        className="mode-opt"
        aria-pressed={mode === 'voice'}
        disabled={disabled || voiceDisabled}
        onClick={() => onChange('voice')}
      >
        <MicIcon />
        음성으로
      </button>
      <button
        type="button"
        className="mode-opt"
        aria-pressed={mode === 'text'}
        disabled={disabled}
        onClick={() => onChange('text')}
      >
        <KeyboardIcon />
        글로
      </button>
    </div>
  )
}
