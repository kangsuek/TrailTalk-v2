// 설정 화면의 순수 규칙(규약 4.1, 시안 설정 01~03). UI·브라우저 API에 의존하지 않는다.

export type ChatModel = 'haiku' | 'sonnet' | 'opus'
export type ThemeMode = 'system' | 'light' | 'dark'

export const MAX_NICKNAME_LENGTH = 20
export const MAX_INTERESTS = 10
export const MAX_INTEREST_LENGTH = 30

export const MODELS: readonly ChatModel[] = ['haiku', 'sonnet', 'opus']

// 서버 기본 모델이 아닌 모델 밑에 보이는 한 마디(시안: haiku 빠르게, opus 깊게)
const MODEL_HINT: Record<ChatModel, string> = { haiku: '빠르게', sonnet: '균형', opus: '깊게' }

export const THEME_CHOICES: readonly { value: ThemeMode; label: string }[] = [
  { value: 'system', label: '시스템 설정 따르기' },
  { value: 'light', label: '라이트' },
  { value: 'dark', label: '다크' },
]

/** 모델 버튼 밑 문구. 서버 기본 모델이면 "기본" */
export function modelHint(model: ChatModel, defaultModel: ChatModel): string {
  return model === defaultModel ? '기본' : MODEL_HINT[model]
}

/** 지금 쓰는 모델. 저장값이 없으면 서버 기본값 */
export function effectiveModel(saved: ChatModel | null, defaultModel: ChatModel): ChatModel {
  return saved ?? defaultModel
}

/** 모델을 고를 때 서버에 보낼 값. 기본 모델을 고르면 null(서버 기본값을 따른다) */
export function modelToSave(choice: ChatModel, defaultModel: ChatModel): ChatModel | null {
  return choice === defaultModel ? null : choice
}

/** 호칭 입력을 서버에 보낼 값으로. 빈 값이면 null(기본 호칭), 앞뒤 공백은 뺀다. 20자를 넘으면 오류 문구 */
export function nicknameToSave(input: string): { value: string | null } | { error: string } {
  const value = input.trim()
  if (value.length > MAX_NICKNAME_LENGTH) {
    return { error: `호칭은 ${MAX_NICKNAME_LENGTH}자까지예요.` }
  }
  if (/[\r\n]/.test(value)) return { error: '호칭은 한 줄로 적어 주세요.' }
  return { value: value === '' ? null : value }
}

/** 관심사를 하나 더한다. 넣을 수 없으면(빈 값·중복·개수 초과) 이유를, 넣었으면 새 목록을 돌려준다 */
export function addInterest(
  interests: readonly string[],
  value: string,
): { interests: string[] } | { error: string } {
  const item = value.trim()
  if (item === '') return { error: '관심사를 입력해 주세요.' }
  if (item.length > MAX_INTEREST_LENGTH) {
    return { error: `관심사는 ${MAX_INTEREST_LENGTH}자까지예요.` }
  }
  if (interests.includes(item)) return { error: '이미 있는 관심사예요.' }
  if (interests.length >= MAX_INTERESTS) return { error: `관심사는 ${MAX_INTERESTS}개까지예요.` }
  return { interests: [...interests, item] }
}

export function removeInterest(interests: readonly string[], value: string): string[] {
  return interests.filter((item) => item !== value)
}

export function isThemeMode(value: unknown): value is ThemeMode {
  return value === 'system' || value === 'light' || value === 'dark'
}
