// 화면 모드(시스템·라이트·다크)를 이 기기에만 기억하고 적용한다(규약 4.1·시안 설정 03).
// 서버에는 저장하지 않는다. 기억은 편의일 뿐이라 접근이 막혀도 앱은 시스템 설정대로 동작한다.
import { isThemeMode, type ThemeMode } from '../core/settings.ts'

const THEME_KEY = 'trailtalk.theme'

export function readTheme(): ThemeMode {
  try {
    const value = localStorage.getItem(THEME_KEY)
    return isThemeMode(value) ? value : 'system'
  } catch {
    return 'system'
  }
}

export function rememberTheme(mode: ThemeMode): void {
  try {
    localStorage.setItem(THEME_KEY, mode)
  } catch {
    // 기억하지 못해도 이번 화면에는 적용된다
  }
}

/** 시스템이면 data-theme을 빼서 prefers-color-scheme을 따르고, 아니면 그 값으로 고정한다(index.css) */
export function applyTheme(mode: ThemeMode, root: HTMLElement = document.documentElement): void {
  if (mode === 'system') delete root.dataset.theme
  else root.dataset.theme = mode
}
