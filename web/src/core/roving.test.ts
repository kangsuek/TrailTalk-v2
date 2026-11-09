import { describe, expect, it } from 'vitest'
import { nextIndexForKey } from './roving.ts'

describe('nextIndexForKey', () => {
  it('오른쪽·아래 화살표는 다음, 왼쪽·위 화살표는 이전으로 움직인다', () => {
    expect(nextIndexForKey('ArrowRight', 0, 3)).toBe(1)
    expect(nextIndexForKey('ArrowDown', 1, 3)).toBe(2)
    expect(nextIndexForKey('ArrowLeft', 2, 3)).toBe(1)
    expect(nextIndexForKey('ArrowUp', 1, 3)).toBe(0)
  })

  it('끝에서 한 칸 더 가면 반대쪽 끝으로 돈다', () => {
    expect(nextIndexForKey('ArrowRight', 2, 3)).toBe(0)
    expect(nextIndexForKey('ArrowLeft', 0, 3)).toBe(2)
  })

  it('Home은 처음, End는 마지막이다', () => {
    expect(nextIndexForKey('Home', 2, 3)).toBe(0)
    expect(nextIndexForKey('End', 0, 3)).toBe(2)
  })

  it('다른 키나 항목이 없으면 움직이지 않는다(null)', () => {
    expect(nextIndexForKey('Enter', 0, 3)).toBeNull()
    expect(nextIndexForKey('a', 0, 3)).toBeNull()
    expect(nextIndexForKey('ArrowRight', 0, 0)).toBeNull()
  })

  it('항목이 하나면 제자리다', () => {
    expect(nextIndexForKey('ArrowRight', 0, 1)).toBe(0)
  })
})
