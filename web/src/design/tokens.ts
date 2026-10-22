// 화면 시안(docs/design/README.md 디자인 요약)의 색. CSS 변수(index.css)와 같은 값이어야 한다
// (tests/tokens.test.ts가 비교한다).
export const LIGHT = {
  bg: '#F3F0E8',
  card: '#FFFFFF',
  text: '#16241D',
  textSub: '#4A5A52',
  primary: '#1D5B43',
  amber: '#9C5C00',
  brick: '#8A2615',
} as const

export const DARK = {
  bg: '#0D1612',
  card: '#17241D',
  text: '#EDEAE0',
  textSub: '#A9B7AE',
  primary: '#4FB58D',
  amber: '#E3A23B',
  brick: '#E8806B',
} as const

export type Palette = Record<keyof typeof LIGHT, string>

// 크기(시안): 큰 버튼 80, 보조 버튼 48, 헤더 60, 하단 탭 64
export const SIZE = { bigButton: 80, subButton: 48, header: 60, tabBar: 64 } as const
