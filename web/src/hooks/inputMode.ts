// "음성으로 / 글로" 방식을 기기에 기억한다(규약 6.6: 고른 방식을 기억해 시작 화면과 대화 화면이 같게 쓴다).
export type InputMode = 'voice' | 'text'

const MODE_KEY = 'trailtalk.mode'

/** 기기에 기억한 방식(없거나 못 읽으면 글). 기억은 편의일 뿐이라 접근이 막혀도 앱은 동작한다 */
export function readMode(): InputMode {
  try {
    return localStorage.getItem(MODE_KEY) === 'voice' ? 'voice' : 'text'
  } catch {
    return 'text'
  }
}

export function rememberMode(mode: InputMode): void {
  try {
    localStorage.setItem(MODE_KEY, mode)
  } catch {
    // 기억하지 못해도 이번 화면은 고른 방식으로 동작한다
  }
}
