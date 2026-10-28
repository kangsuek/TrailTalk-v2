// 이 기기에서 진행 중이던 대화의 ID를 기억한다(새로고침 뒤 복원, docs/client-contract.md 2.11).
// 저장소를 쓸 수 없거나 막혀 있어도 앱은 그대로 돈다.
const KEY = 'trailtalk.activeSession'

export function readRememberedSession(): string | null {
  try {
    return window.localStorage.getItem(KEY)
  } catch {
    return null
  }
}

export function writeRememberedSession(sessionId: string | null): void {
  try {
    if (sessionId) window.localStorage.setItem(KEY, sessionId)
    else window.localStorage.removeItem(KEY)
  } catch {
    // 저장소를 쓸 수 없으면 복원만 못 한다
  }
}

/** 기억한 값이 이 세션일 때만 지운다(다른 탭이 기억한 다른 세션은 지우지 않는다). */
export function forgetRememberedSession(sessionId: string): void {
  if (readRememberedSession() === sessionId) writeRememberedSession(null)
}
