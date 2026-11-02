import { describe, expect, it } from 'vitest'
import {
  addInterest,
  effectiveModel,
  isThemeMode,
  modelHint,
  modelToSave,
  nicknameToSave,
  removeInterest,
} from './settings.ts'

describe('호칭', () => {
  it('앞뒤 공백을 빼고, 비면 기본 호칭(null)으로 돌린다', () => {
    expect(nicknameToSave('  다니엘 ')).toEqual({ value: '다니엘' })
    expect(nicknameToSave('   ')).toEqual({ value: null })
  })

  it('20자까지만 받고 한 줄이어야 한다', () => {
    expect(nicknameToSave('가'.repeat(20))).toEqual({ value: '가'.repeat(20) })
    expect(nicknameToSave('가'.repeat(21))).toEqual({ error: '호칭은 20자까지예요.' })
    expect(nicknameToSave('가\n나')).toEqual({ error: '호칭은 한 줄로 적어 주세요.' })
  })
})

describe('관심사', () => {
  it('앞뒤 공백을 뺀 값을 끝에 더한다', () => {
    expect(addInterest(['전시'], ' 등산 ')).toEqual({ interests: ['전시', '등산'] })
  })

  it('빈 값·중복·30자 초과·10개 초과는 이유를 돌려준다', () => {
    expect(addInterest([], '  ')).toEqual({ error: '관심사를 입력해 주세요.' })
    expect(addInterest(['전시'], '전시')).toEqual({ error: '이미 있는 관심사예요.' })
    expect(addInterest([], '가'.repeat(31))).toEqual({ error: '관심사는 30자까지예요.' })
    expect(addInterest([], '가'.repeat(30))).toEqual({ interests: ['가'.repeat(30)] })
    const ten = Array.from({ length: 10 }, (_, i) => `관심${i}`)
    expect(addInterest(ten, '하나 더')).toEqual({ error: '관심사는 10개까지예요.' })
  })

  it('지우면 그 항목만 빠진다', () => {
    expect(removeInterest(['전시', '테크', '등산'], '테크')).toEqual(['전시', '등산'])
  })
})

describe('대화 모델', () => {
  it('저장값이 없으면 서버 기본 모델을 쓴다', () => {
    expect(effectiveModel(null, 'sonnet')).toBe('sonnet')
    expect(effectiveModel('opus', 'sonnet')).toBe('opus')
  })

  it('기본 모델을 고르면 null을 보내 서버 기본값을 따른다', () => {
    expect(modelToSave('sonnet', 'sonnet')).toBeNull()
    expect(modelToSave('haiku', 'sonnet')).toBe('haiku')
  })

  it('기본 모델 밑에는 "기본", 나머지는 한 마디가 붙는다', () => {
    expect(modelHint('sonnet', 'sonnet')).toBe('기본')
    expect(modelHint('haiku', 'sonnet')).toBe('빠르게')
    expect(modelHint('opus', 'sonnet')).toBe('깊게')
    expect(modelHint('sonnet', 'haiku')).toBe('균형')
  })
})

describe('화면 모드', () => {
  it('세 값만 받는다', () => {
    expect(['system', 'light', 'dark'].every(isThemeMode)).toBe(true)
    expect(isThemeMode('auto')).toBe(false)
    expect(isThemeMode(null)).toBe(false)
  })
})
