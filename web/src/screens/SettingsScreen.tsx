// 설정 화면(시안 설정 01·02·03, FR-17): 호칭·관심사, 대화 모델, 화면 모드, 앱 정보.
// 값을 바꾸면 바로 PUT /api/profile로 저장하고 헤더 오른쪽에 "저장됨"을 보인다. 검증 오류(422)는
// 그 필드 옆에 보이고 값을 서버 값으로 되돌린다. 보이스·말 속도·맞장구·음성 원본 보관은 자체 음성이
// 보류(D9)라 만들지 않는다.
import { useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from 'react'
import { ApiError } from '../api/http.ts'
import { getProfile, updateProfile, type Profile, type ProfilePatch } from '../api/profile.ts'
import { CONNECTION_LABEL, type Connection } from '../core/connection.ts'
import { nextIndexForKey } from '../core/roving.ts'
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
import { useAppUpdate } from '../hooks/appUpdate.ts'
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
  const { updateReady, applyUpdate } = useAppUpdate()
  // 선택 묶음(라디오)은 체크된 항목만 탭 순서에 두고 화살표 키로 옆 항목을 고른다(roving tabindex)
  const modelButtons = useRef<(HTMLButtonElement | null)[]>([])
  const themeButtons = useRef<(HTMLButtonElement | null)[]>([])
  const onRadioKey = (
    event: KeyboardEvent<HTMLButtonElement>,
    buttons: { current: (HTMLButtonElement | null)[] },
    index: number,
    choose: (next: number) => void,
  ) => {
    const next = nextIndexForKey(event.key, index, buttons.current.length)
    if (next === null) return
    event.preventDefault()
    choose(next)
    buttons.current[next]?.focus()
  }
  const [errors, setErrors] = useState<FieldErrors>({})
  const [nickname, setNickname] = useState('')
  const [interestInput, setInterestInput] = useState('')
  const [theme, setTheme] = useState<ThemeMode>(readTheme)
  // 저장은 한 번에 하나씩 순서대로 보낸다(빠르게 연달아 바꿔도 앞의 값이 뒤를 덮지 않게)
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const latest = useRef<Profile | null>(null)
  const pending = useRef(0) // 보내려고 줄 선 저장 수
  const nicknameText = useRef('') // 호칭 입력의 현재 값(저장이 끝난 뒤 그 사이 더 입력했는지 보려고)

  useEffect(() => {
    const controller = new AbortController()
    getProfile(controller.signal)
      .then((loaded) => {
        // 계약과 다른 응답(터널·프록시가 준 엉뚱한 본문 등)이면 화면이 죽지 않게 불러오기 실패로 본다
        if (!Array.isArray(loaded?.interests)) throw new Error('unexpected profile response')
        latest.current = loaded
        setProfile(loaded)
        nicknameText.current = loaded.nickname ?? ''
        setNickname(loaded.nickname ?? '')
      })
      .catch((error) => {
        if (!controller.signal.aborted) setLoadError(errorText(error))
      })
    return () => controller.abort()
  }, [attempt])

  /**
   * 바뀐 필드만 저장한다. 보낼 값은 차례가 됐을 때의 최신 프로필로 만든다(앞의 저장이 끝난 결과를 바탕으로
   * 해야 연달아 누른 변경이 서로 덮어쓰지 않는다). build가 null이면 저장할 것이 없는 것이고, 오류 문구를
   * 주면 서버에 보내지 않고 그 필드 옆에 보인다. 성공(또는 할 일 없음)이면 true
   */
  const commit = (
    field: Field,
    build: (current: Profile) => ProfilePatch | { error: string } | null,
  ): Promise<boolean> => {
    pending.current += 1
    setSave('saving')
    const run = queue.current.then(async () => {
      let ok = true
      let invalid = false // 서버에 보내기 전에 걸러진 입력 오류(저장을 시도하지 않았다)
      try {
        const current = latest.current
        const patch = current ? build(current) : null
        if (patch !== null && 'error' in patch && typeof patch.error === 'string') {
          setErrors((e) => ({ ...e, [field]: patch.error as string }))
          ok = false
          invalid = true
        } else if (patch !== null) {
          const next = await updateProfile(patch as ProfilePatch)
          latest.current = next
          setProfile(next)
          setErrors((e) => ({ ...e, [field]: undefined }))
        } else {
          setErrors((e) => ({ ...e, [field]: undefined }))
        }
      } catch (error) {
        setErrors((e) => ({ ...e, [field]: errorText(error) }))
        ok = false
      }
      // 대기 중인 저장이 모두 끝났을 때만 결과를 보인다. 입력 오류는 필드 옆 문구로 충분하고, 저장을
      // 시도하지 않았으니 "저장 안 됨"은 서버가 거절하거나 연결이 안 됐을 때만 쓴다
      pending.current -= 1
      if (pending.current === 0) setSave(invalid ? 'idle' : ok ? 'saved' : 'failed')
      return ok
    })
    queue.current = run
    return run
  }

  const saveNickname = async () => {
    if (!latest.current) return
    const sent = nickname
    const parsed = nicknameToSave(sent)
    if ('error' in parsed) {
      setErrors((e) => ({ ...e, nickname: parsed.error }))
      nicknameText.current = latest.current.nickname ?? ''
      setNickname(nicknameText.current) // 값을 되돌린다
      return
    }
    await commit('nickname', (current) =>
      parsed.value === current.nickname ? null : { nickname: parsed.value },
    )
    // 그 사이 더 입력하지 않았을 때만 서버가 받은 값(공백을 뺀 값, 거절됐으면 이전 값)으로 입력을 맞춘다
    if (nicknameText.current === sent) {
      nicknameText.current = latest.current?.nickname ?? ''
      setNickname(nicknameText.current)
    }
  }

  const onNicknameKey = (event: KeyboardEvent<HTMLInputElement>) => {
    const composing = event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229
    if (event.key === 'Enter' && !composing) {
      event.preventDefault()
      void saveNickname()
    }
  }

  const add = async () => {
    const value = interestInput
    const ok = await commit('interests', (current) => {
      const added = addInterest(current.interests, value)
      return 'error' in added ? { error: added.error } : { interests: added.interests }
    })
    if (ok) setInterestInput((now) => (now === value ? '' : now))
  }

  const onInterestKey = (event: KeyboardEvent<HTMLInputElement>) => {
    const composing = event.nativeEvent.isComposing || event.nativeEvent.keyCode === 229
    if (event.key === 'Enter' && !composing) {
      event.preventDefault()
      void add()
    }
  }

  const remove = (item: string) => {
    void commit('interests', (current) => ({ interests: removeInterest(current.interests, item) }))
  }

  const chooseModel = (choice: ChatModel) => {
    void commit('chat_model', (current) => {
      const next = modelToSave(choice, current.default_chat_model)
      return next === current.chat_model ? null : { chat_model: next }
    })
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
              onChange={(event) => {
                nicknameText.current = event.target.value
                setNickname(event.target.value)
              }}
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
              {MODELS.map((model, index) => {
                const on = effectiveModel(profile.chat_model, profile.default_chat_model) === model
                return (
                  <button
                    key={model}
                    ref={(node) => {
                      modelButtons.current[index] = node
                    }}
                    type="button"
                    role="radio"
                    aria-checked={on}
                    tabIndex={on ? 0 : -1}
                    className="set-seg-btn"
                    onClick={() => chooseModel(model)}
                    onKeyDown={(event) =>
                      onRadioKey(event, modelButtons, index, (next) => chooseModel(MODELS[next]))
                    }
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
              {THEME_CHOICES.map((choice, index) => (
                <button
                  key={choice.value}
                  ref={(node) => {
                    themeButtons.current[index] = node
                  }}
                  type="button"
                  role="radio"
                  aria-checked={theme === choice.value}
                  tabIndex={theme === choice.value ? 0 : -1}
                  className="set-radio"
                  onClick={() => chooseTheme(choice.value)}
                  onKeyDown={(event) =>
                    onRadioKey(event, themeButtons, index, (next) =>
                      chooseTheme(THEME_CHOICES[next].value),
                    )
                  }
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
            {updateReady && (
              <div className="set-update" role="status">
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M20 12a8 8 0 1 1-2.5-5.8M20 4v5h-5" />
                </svg>
                <span className="set-update-text">
                  새 버전이 있어요
                  <small>대화가 끝난 뒤에 적용하는 게 좋아요</small>
                </span>
                <button type="button" onClick={applyUpdate}>
                  적용
                </button>
              </div>
            )}
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
