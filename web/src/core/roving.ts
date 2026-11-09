// 화살표 키로 같은 묶음의 항목 사이를 옮기는 순수 계산(roving tabindex). 하단 메뉴와 설정의 모델·화면 모드
// 선택이 쓴다. 옮길 키가 아니면 null이다.

export function nextIndexForKey(key: string, current: number, count: number): number | null {
  if (count <= 0) return null
  switch (key) {
    case 'ArrowRight':
    case 'ArrowDown':
      return (current + 1) % count
    case 'ArrowLeft':
    case 'ArrowUp':
      return (current - 1 + count) % count
    case 'Home':
      return 0
    case 'End':
      return count - 1
    default:
      return null
  }
}
