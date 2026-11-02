// 설정 화면(시안 설정 01·02·03, FR-17): 호칭·관심사, 대화 모델, 화면 모드, 앱 정보.
// 값을 바꾸면 바로 PUT /api/profile로 저장하고 헤더 오른쪽에 "저장됨"을 보인다. 검증 오류(422)는
// 그 필드 옆에 보이고 값을 서버 값으로 되돌린다. 보이스·말 속도·맞장구·음성 원본 보관은 자체 음성이
// 보류(D9)라 만들지 않는다.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { ApiError } from '../api/http.ts'
import { getProfile, updateProfile, type Profile, type ProfilePatch } from '../api/profile.ts'
import { CONNECTION_LABEL, type Connection } from '../core/connection.ts'
import {
  MAX_INTERESTS,
  MAX_INTEREST_LENGTH,
  MAX_NICKNAME_LENGTH,
  MODELS,
  THEME_CHOICES,
  addInterest,
  effectiveModel,
  modelHint,
  modelToSave,
  nicknameToSave,
  removeInterest,
  type ChatModel,
  type ThemeMode,
} from '../core/settings.ts'
import { applyTheme, readTheme, rememberTheme } from '../hooks/theme.ts'

type Field = 'nickname' | 'interests' | 'chat_model'
type SaveState = 'idle' | 'saving' | 'saved' | 'failed'
type FieldErrors = Partial<Record<Field, string>>

const errorText = (error: unknown): string =>
  error instanceof ApiError ? error.message : '저장하지 못했어요. 다시 해 주세요.'

const SAVE_LABEL: Record<Exclude<SaveState, 'idle'>, string> = {
  saving: '저장 중…',
  saved: '저장됨',
  failed: '저장 안 됨',
}

// 화면 모드 옆의 색 견본(시안 설정 03)
const THEME_SWATCH: Record<ThemeMode, ('light' | 'dark')[]> = {
  system: ['light', 'dark'],
  light: ['light'],
  dark: ['dark'],
}

interface Props {
  connection: Connection
}

export default function SettingsScreen({ connection }: Props) {
  const [profile, setProfile] = useState<Profile | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [save, setSave] = useState<SaveState>('idle')
  const [errors, setErrors] = useState<FieldErrors>({})
  const [nickname, setNickname] = useState('')
  const [interestInput, setInterestInput] = useState('')
  const [theme, setTheme] = useState<ThemeMode>(readTheme)
  // 저장은 한 번에 하나씩 순서대로 보낸다(빠르게 연달아 바꿔도 앞의 값이 뒤를 덮지 않게)
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const latest = useRef<Profile | null>(null)

  useEffect(() => {
    const controller = new AbortController()
    getProfile(controller.signal)
      .then((loaded) => {
        // 계약과 다른 응답(터널·프록시가 준 엉뚱한 본문 등)이면 화면이 죽지 않게 불러오기 실패로 본다
        if (!Array.isArray(loaded?.interests)) throw new Error('unexpected profile response')
        latest.current = loaded
        setProfile(loaded)
        setNickname(loaded.nickname ?? '')
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoadError(errorText(error))
      })
    return () => controller.abort()
  }, [attempt])

  /** 바뀐 필드만 저장한다. 성공하면 true, 실패하면 그 필드 옆에 이유를 보이고 false */
  const commit = (field: Field, patch: ProfilePatch): Promise<boolean> => {
    setSave('saving')
    const run = queue.current.then(async () => {
      try {
        const next = await updateProfile(patch)
        latest.current = next
        setProfile(next)
        setErrors((current) => ({ ...current, [field]: undefined }))
        setSave('saved')
        return true
      } catch (error) {
        setErrors((current) => ({ ...current, [field]: errorText(error) }))
        setSave('failed')
        return false
      }
    })
    queue.current = run
    return run
  }

  const saveNickname = async () => {
    const current = latest.current
    if (!current) return
    const parsed = nicknameToSave(nickname)
    if ('error' in parsed) {
      setErrors((e) => ({ ...e, nickname: parsed.error }))
      setNickname(current.nickname ?? '') // 값을 되돌린다
      return
    }
    if (parsed.value === current.nickname) {
      setErrors((e) => ({ ...e, nickname: undefined }))
      setNickname(current.nickname ?? '')
      return
    }
    await commit('nickname', { nickname: parsed.value })
    // 서버가 받은 값(공백을 뺀 값)으로, 받지 않았으면 이전 서버 값으로 입력을 맞춘다
    setNickname(latest.current?.nickname ?? '')
  }

  const onNicknameKey = (event: KeyboardEvent<HTMLInputElement>) => {
    const composing = event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229
    if (event.key === 'Enter' && !composing) {
      event.preventDefault()
      void saveNickname()
    }
  }

  const add = async () => {
    const current = latest.current
    if (!current) return
    const added = addInterest(current.interests, interestInput)
    if ('error' in added) {
      setErrors((e) => ({ ...e, interests: added.error }))
      return
    }
    if (await commit('interests', { interests: added.interests })) setInterestInput('')
  }

  const onInterestKey = (event: KeyboardEvent<HTMLInputElement>) => {
    const composing = event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229
    if (event.key === 'Enter' && !composing) {
      event.preventDefault()
      void add()
    }
  }

  const remove = (item: string) => {
    const current = latest.current
    if (!current) return
    void commit('interests', { interests: removeInterest(current.interests, item) })
  }

  const chooseModel = (choice: ChatModel) => {
    const current = latest.current
    if (!current) return
    const next = modelToSave(choice, current.default_chat_model)
    if (next === current.chat_model) return
    void commit('chat_model', { chat_model: next })
  }

  const chooseTheme = (mode: ThemeMode) => {
    setTheme(mode)
    rememberTheme(mode)
    applyTheme(mode)
  }

  const label = CONNECTION_LABEL[connection]

  return (
    <section className="settings" aria-label="설정">
      <header className="hd2">
        <h1 className="ttl">설정</h1>
        <span className="set-saved" aria-live="polite">
          {save !== 'idle' && (
            <>
              {save === 'saved' && (
                <svg className="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M5 12l4 4 10-10" />
                </svg>
              )}
              {SAVE_LABEL[save]}
            </>
          )}
        </span>
      </header>

      {profile === null ? (
        loadError ? (
          <div className="set-note">
            <p role="alert">{loadError}</p>
            <button
              type="button"
              className="btn"
              onClick={() => {
                setLoadError(null)
                setAttempt((n) => n + 1)
              }}
            >
              다시 불러오기
            </button>
          </div>
        ) : (
          <p className="set-note">불러오는 중…</p>
        )
      ) : (
        <div className="set-body">
          <Section label="내 정보">
            <label className="set-label" htmlFor="set-nickname">
              호칭
            </label>
            <div className="set-desc">
              캐릭터가 대화를 시작할 때 이렇게 불러요. 첫 인사에서만 써요.
            </div>
            <input
              id="set-nickname"
              className="set-input"
              value={nickname}
              placeholder="기본 호칭"
              aria-invalid={errors.nickname ? true : undefined}
              aria-describedby="set-nickname-hint"
              onChange={(event) => setNickname(event.target.value)}
              onBlur={() => void saveNickname()}
              onKeyDown={onNicknameKey}
            />
            <div className="set-hint" id="set-nickname-hint">
              <span>1~{MAX_NICKNAME_LENGTH}자</span>
              <span>
                {nickname.trim().length} / {MAX_NICKNAME_LENGTH}
              </span>
            </div>
            {errors.nickname && (
              <div className="set-error" role="alert">
                {errors.nickname}
              </div>
            )}
          </Section>

          <Section label="관심사">
            <div className="set-row">
              <span className="set-label">관심사</span>
              <span className="set-desc">
                {profile.interests.length} / {MAX_INTERESTS}
              </span>
            </div>
            <div className="set-desc">대화에서 이야기를 이어 갈 때 참고해요.</div>
            {profile.interests.length > 0 && (
              <ul className="set-chips" aria-label="관심사 목록">
                {profile.interests.map((item) => (
                  <li key={item} className="set-chip">
                    {item}
                    <button
                      type="button"
                      aria-label={`${item} 지우기`}
                      onClick={() => remove(item)}
                    >
                      <svg className="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true">
                        <path d="M6 6l12 12M18 6L6 18" />
                      </svg>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <div className="set-add">
              <input
                className="set-input"
                aria-label="관심사 추가"
                placeholder={`관심사 추가 (${MAX_INTEREST_LENGTH}자 이내)`}
                value={interestInput}
                aria-invalid={errors.interests ? true : undefined}
                onChange={(event) => {
                  setInterestInput(event.target.value)
                  setErrors((e) => ({ ...e, interests: undefined }))
                }}
                onKeyDown={onInterestKey}
              />
              <button
                type="button"
                className="btn btn-primary set-add-btn"
                onClick={() => void add()}
              >
                추가
              </button>
            </div>
            {errors.interests && (
              <div className="set-error" role="alert">
                {errors.interests}
              </div>
            )}
          </Section>

          <Section label="대화 모델">
            <span className="set-label" id="set-model-label">
              대화 모델
            </span>
            <div className="set-seg" role="radiogroup" aria-labelledby="set-model-label">
              {MODELS.map((model) => {
                const on = effectiveModel(profile.chat_model, profile.default_chat_model) === model
                return (
                  <button
                    key={model}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    className="set-seg-btn"
                    onClick={() => chooseModel(model)}
                  >
                    <b>{model}</b>
                    <span>{modelHint(model, profile.default_chat_model)}</span>
                  </button>
                )
              })}
            </div>
            <div className="set-desc">
              대화 중에도 바꿀 수 있고, 다음 답변부터 써요. 바꾼 직후 첫 답변은 조금 늦을 수 있어요.
            </div>
            {errors.chat_model && (
              <div className="set-error" role="alert">
                {errors.chat_model}
              </div>
            )}
          </Section>

          <Section label="화면 모드">
            <span className="set-label" id="set-theme-label">
              화면 모드
            </span>
            <div className="set-radios" role="radiogroup" aria-labelledby="set-theme-label">
              {THEME_CHOICES.map((choice) => (
                <button
                  key={choice.value}
                  type="button"
                  role="radio"
                  aria-checked={theme === choice.value}
                  className="set-radio"
                  onClick={() => chooseTheme(choice.value)}
                >
                  <span className="set-dot" aria-hidden="true" />
                  <span className="set-radio-name">{choice.label}</span>
                  <span className="set-swatches" aria-hidden="true">
                    {THEME_SWATCH[choice.value].map((tone) => (
                      <i key={tone} data-tone={tone} />
                    ))}
                  </span>
                </button>
              ))}
            </div>
            <div className="set-desc">
              이 기기에만 적용돼요. 해 질 녘이나 밤 산책에는 다크가 눈이 편해요.
            </div>
          </Section>

          <Section label="앱 정보">
            <span className="set-label">앱</span>
            <div className="set-kv">
              <span>서버 연결</span>
              <span className="set-conn" data-state={connection}>
                <i aria-hidden="true" />
                {label.text}
              </span>
            </div>
            <div className="set-kv">
              <span>캐릭터</span>
              <span className="set-desc">{profile.persona_id} · 설정 파일로 바꿔요</span>
            </div>
            <div className="set-kv">
              <span>버전</span>
              <span className="set-desc">TrailTalk v2</span>
            </div>
          </Section>
        </div>
      )}
    </section>
  )
}

function Section({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="set-sec" aria-label={label}>
      {children}
    </section>
  )
}
