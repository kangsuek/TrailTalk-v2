import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { InlineMarkdown } from '../components/Markdown.tsx'
import Transcript from '../components/Transcript.tsx'
import { endSession, reopenSession, type SessionReopened } from '../api/conversation.ts'
import { ApiError } from '../api/http.ts'
import {
  deleteJournal,
  getJournal,
  renameJournal,
  retryJournal,
  updateNote,
  type NotePatch,
} from '../api/journal.ts'
import {
  KIND_LABEL,
  TITLE_FALLBACK,
  TITLE_MAX,
  canReformat,
  cardKind,
  countPills,
  dateLabel,
  isSafeUrl,
  metaLine,
  orderNotes,
  sectionsOf,
  titleOf,
  type CitedLine,
  type JournalDetail,
  type Note,
} from '../core/journal.ts'
import { usePendingPoll } from '../hooks/usePendingPoll.ts'

interface Props {
  id: string
  /** 이 앱(대화 화면)이 지금 들고 있는 진행 중 대화 */
  activeSessionId: string | null
  onBack: () => void
  onOpenChat: () => void
  /** 다시 열기가 끝났다. 호출한 쪽이 대화 화면으로 넘어간다 */
  onResume: (reopened: SessionReopened, options?: { navigate?: boolean }) => void
  onDeleted: () => void
}

const errorText = (error: unknown): string =>
  error instanceof ApiError ? error.message : '문제가 생겼어요. 다시 해 주세요.'

function Cites({ numbers }: { numbers: number[] }) {
  if (numbers.length === 0) return null
  return <sup className="cite">{numbers.map((n) => `[${n}]`).join('')}</sup>
}

function Icon({ children, size }: { children: ReactNode; size?: number }) {
  return (
    <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" width={size} height={size}>
      {children}
    </svg>
  )
}

const BULLET = <circle cx="12" cy="12" r="5" fill="currentColor" />
const QUESTION = (
  <>
    <circle cx="12" cy="12" r="9" />
    <path d="M9.5 9.5a2.5 2.5 0 1 1 3.5 2.3c-.7.4-1 1-1 1.7M12 17h.01" />
  </>
)

function Lines({ lines, icon, tone }: { lines: CitedLine[]; icon: ReactNode; tone: 'primary' | 'amber' }) {
  return (
    <ul className="d-ul">
      {lines.map((line, index) => (
        <li key={index}>
          <span className="d-mark" data-tone={tone}>
            <Icon size={tone === 'amber' ? 18 : 14}>{icon}</Icon>
          </span>
          <span className="d-text">
            <InlineMarkdown text={line.text} />
            <Cites numbers={line.cites} />
          </span>
        </li>
      ))}
    </ul>
  )
}

interface NoteRowProps {
  note: Note
  editable: boolean
  onPatch: (note: Note, patch: NotePatch) => void
  onSave: (note: Note, content: string) => Promise<string | null>
}

function NoteRow({ note, editable, onPatch, onSave }: NoteRowProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(note.content)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    const content = draft.trim()
    if (!content) return
    setSaving(true)
    const failure = await onSave(note, content)
    setSaving(false)
    if (failure) setError(failure)
    else {
      setError(null)
      setEditing(false)
    }
  }

  if (editing) {
    return (
      <li className="note note-edit">
        <label className="sr-only" htmlFor={`note-${note.id}`}>
          {KIND_LABEL[note.kind]} 내용
        </label>
        <textarea
          id={`note-${note.id}`}
          rows={3}
          maxLength={500}
          value={draft}
          autoFocus
          onChange={(event) => setDraft(event.target.value)}
        />
        {error && (
          <p className="chat-error" role="alert">
            {error}
          </p>
        )}
        <div className="note-actions">
          <button
            type="button"
            className="btn"
            onClick={() => {
              setEditing(false)
              setDraft(note.content)
              setError(null)
            }}
          >
            취소
          </button>
          <button
            type="button"
            className="btn btn-primary"
            disabled={saving || !draft.trim()}
            onClick={() => void save()}
          >
            {saving ? '저장하는 중…' : '저장'}
          </button>
        </div>
      </li>
    )
  }

  const idea = note.kind === 'idea'
  const closable = note.kind !== 'memo'
  return (
    <li className="note" data-done={note.done}>
      {closable && (
        <button
          type="button"
          className="ib"
          disabled={!editable}
          aria-label={note.done ? '완료 취소' : '완료로 표시'}
          aria-pressed={note.done}
          onClick={() => onPatch(note, { done: !note.done })}
        >
          <Icon>
            {note.kind === 'todo' ? (
              note.done ? (
                <>
                  <rect x="4" y="4" width="16" height="16" rx="4" />
                  <path d="M8 12l3 3 5-6" />
                </>
              ) : (
                <rect x="4" y="4" width="16" height="16" rx="4" />
              )
            ) : note.done ? (
              <>
                <circle cx="12" cy="12" r="9" />
                <path d="M8 12l3 3 5-6" />
              </>
            ) : (
              <circle cx="12" cy="12" r="9" />
            )}
          </Icon>
        </button>
      )}
      <span className="nt">
        <InlineMarkdown text={note.content} />
        <Cites numbers={note.cites} />
      </span>
      {note.done && <span className="pill pill-idea">완료</span>}
      {idea && (
        <button
          type="button"
          className="ib ib-star"
          disabled={!editable}
          aria-label={note.starred ? '별표 해제' : '별표'}
          aria-pressed={note.starred}
          data-on={note.starred}
          onClick={() => onPatch(note, { starred: !note.starred })}
        >
          <svg className="ic" viewBox="0 0 24 24" aria-hidden="true" style={note.starred ? { fill: 'currentColor' } : undefined}>
            <path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z" />
          </svg>
        </button>
      )}
      <button
        type="button"
        className="ib"
        disabled={!editable}
        aria-label={`${KIND_LABEL[note.kind]} 수정`}
        onClick={() => {
          setDraft(note.content)
          setEditing(true)
        }}
      >
        <Icon>
          <path d="M4 20h4L19 9l-4-4L4 16zM13 7l4 4" />
        </Icon>
      </button>
    </li>
  )
}

export default function JournalDetailScreen({
  id,
  activeSessionId,
  onBack,
  onOpenChat,
  onResume,
  onDeleted,
}: Props) {
  const [detail, setDetail] = useState<JournalDetail | null>(null)
  const [missing, setMissing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<'reopen' | 'end' | 'retry' | 'delete' | null>(null)
  const [openingMode, setOpeningMode] = useState<'text' | 'voice'>('text') // 다시 여는 중인 방식(버튼 문구)
  const [menuOpen, setMenuOpen] = useState(false)
  const [titleOpen, setTitleOpen] = useState(false)
  const [titleDraft, setTitleDraft] = useState('')
  const [titleError, setTitleError] = useState<string | null>(null)
  const [titleSaving, setTitleSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [transcriptOpen, setTranscriptOpen] = useState<boolean | null>(null)
  const aborter = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  const load = useCallback(
    async (silent: boolean) => {
      aborter.current?.abort()
      const controller = (aborter.current = new AbortController())
      try {
        const next = await getJournal(id, controller.signal)
        setDetail(next)
        setMissing(false)
        setError(null)
      } catch (caught) {
        if (controller.signal.aborted) return
        if (caught instanceof ApiError && caught.code === 'session_not_found') setMissing(true)
        else if (!silent) setError(errorText(caught))
      }
    },
    [id],
  )

  // id가 바뀌면 호출한 쪽이 key로 새로 마운트하므로 상태를 비우지 않는다
  useEffect(() => {
    void load(false)
    return () => aborter.current?.abort()
  }, [load])

  usePendingPoll(detail?.session.journal_status === 'pending', () => void load(true))

  if (missing) {
    return (
      <section className="journal" aria-label="일지 상세">
        <header className="hd2 hd2-detail">
          <button type="button" className="ib" aria-label="목록으로" onClick={onBack}>
            <Icon>
              <path d="M15 6l-6 6 6 6" />
            </Icon>
          </button>
          <span className="hd-title">일지</span>
          <span className="ib" aria-hidden="true" />
        </header>
        <p className="j-empty" role="alert">
          이 일지를 찾을 수 없어요. 이미 지워졌을 수 있어요.
        </p>
      </section>
    )
  }

  const session = detail?.session
  const kind = session ? cardKind(session) : null
  const sections = detail ? sectionsOf(detail) : null
  const isOpenHere = session?.id === activeSessionId
  const otherOpen = activeSessionId !== null && !isOpenHere
  const unopenedActive = kind === 'active' && !isOpenHere
  const noteGroups = detail
    ? (['idea', 'todo', 'memo'] as const).map((k) => ({ kind: k, notes: orderNotes(detail.notes, k) }))
    : []

  async function patchNote(note: Note, patch: NotePatch) {
    const apply = (next: Partial<Note>) =>
      setDetail((current) =>
        current && {
          ...current,
          notes: current.notes.map((n) => (n.id === note.id ? { ...n, ...next } : n)),
        },
      )
    apply(patch as Partial<Note>)
    setNotice(null)
    try {
      apply(await updateNote(note.id, patch))
    } catch (caught) {
      // 서버에 반영되지 못한 필드만 되돌린다(그사이 보낸 다른 변경은 건드리지 않는다)
      apply(Object.fromEntries(Object.keys(patch).map((key) => [key, note[key as keyof Note]])))
      setNotice(errorText(caught))
    }
  }

  async function saveNote(note: Note, content: string): Promise<string | null> {
    try {
      const saved = await updateNote(note.id, { content })
      setDetail(
        (current) =>
          current && { ...current, notes: current.notes.map((n) => (n.id === saved.id ? saved : n)) },
      )
      return null
    } catch (caught) {
      return errorText(caught)
    }
  }

  async function run(action: NonNullable<typeof busy>, task: () => Promise<void>) {
    setBusy(action)
    setNotice(null)
    try {
      await task()
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setBusy(null)
    }
  }

  const resume = (mode: 'text' | 'voice') => {
    setOpeningMode(mode)
    return run('reopen', async () => {
      // 기다리는 사이 화면을 떠났어도 서버에서 이미 다시 열렸으니 대화 화면에 넘기되 갑자기 이동하지 않는다
      onResume(await reopenSession(id, mode), { navigate: mounted.current })
    })
  }

  const endNow = () =>
    run('end', async () => {
      await endSession(id) // 정리를 최대 45초 기다린다. 끝나지 않으면 pending으로 돌아온다
      await load(true)
    })

  const retry = () =>
    run('retry', async () => {
      await retryJournal(id)
      await load(true)
    })

  const remove = () =>
    run('delete', async () => {
      setConfirmDelete(false)
      await deleteJournal(id)
      onDeleted()
    })

  async function saveTitle() {
    const title = titleOf(titleDraft)
    if (!title) return
    setTitleSaving(true)
    try {
      const next = await renameJournal(id, title)
      setDetail((current) => current && { ...current, session: next })
      setTitleOpen(false)
      setTitleError(null)
    } catch (caught) {
      setTitleError(errorText(caught))
    } finally {
      setTitleSaving(false)
    }
  }

  const showTranscript = transcriptOpen ?? (kind === 'failed' || kind === 'unorganized')
  // 진행 중이거나 이 앱이 열고 있는 대화는 끝낸 뒤 지운다(열고 있는 대화를 지우면 화면이 지워진 세션을 든다)
  const canDelete = !!session && session.status !== 'active' && !isOpenHere
  const pills = session ? countPills(session.counts) : []
  const hasNotes = !!detail && detail.notes.length > 0

  return (
    <section className="journal" aria-label="일지 상세">
      <header className="hd2 hd2-detail">
        <button type="button" className="ib" aria-label="목록으로" onClick={onBack}>
          <Icon>
            <path d="M15 6l-6 6 6 6" />
          </Icon>
        </button>
        <span className="hd-title">일지</span>
        <button
          type="button"
          className="ib"
          aria-label="더 보기"
          aria-haspopup="menu"
          aria-expanded={menuOpen}
          disabled={!detail}
          onClick={() => setMenuOpen((open) => !open)}
        >
          <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="5" r="1.4" />
            <circle cx="12" cy="12" r="1.4" />
            <circle cx="12" cy="19" r="1.4" />
          </svg>
        </button>
      </header>

      {menuOpen && session && (
        <>
          <button type="button" className="menu-back" aria-label="메뉴 닫기" onClick={() => setMenuOpen(false)} />
          <div className="menu" role="menu">
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false)
                setTitleDraft(session.title ?? '')
                setTitleError(null)
                setTitleOpen(true)
              }}
            >
              제목 수정
            </button>
            <button
              type="button"
              role="menuitem"
              className="menu-danger"
              disabled={!canDelete}
              onClick={() => {
                setMenuOpen(false)
                setConfirmDelete(true)
              }}
            >
              {canDelete ? '대화 지우기' : '대화 지우기 (끝낸 뒤)'}
            </button>
          </div>
        </>
      )}

      <div className="j-body">
        {!detail && !error && <p className="j-empty">불러오는 중…</p>}
        {error && (
          <div className="j-empty" role="alert">
            <p>{error}</p>
            <button type="button" className="btn" onClick={() => void load(false)}>
              다시 불러오기
            </button>
          </div>
        )}

        {detail && session && sections && (
          <>
            <div className="d-head">
              <div className="d-meta">
                {dateLabel(session.date)} {metaLine(session)}
              </div>
              <h1 className="d-title">{session.title ?? TITLE_FALLBACK}</h1>
              {pills.length > 0 && (
                <div className="j-pills">
                  {pills.map((pill) => (
                    <span key={pill.kind} className={`pill pill-${pill.kind}`}>
                      {pill.text}
                    </span>
                  ))}
                </div>
              )}
            </div>

            {kind === 'pending' && (
              <>
                <section className="banner banner-amber" role="status" aria-label="정리 중">
                  <div className="banner-row">
                    <svg className="ic j-spin" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M12 3a9 9 0 1 0 9 9" />
                    </svg>
                    <div>
                      <div className="banner-title">일지를 정리하고 있어요</div>
                      <div className="banner-sub">끝나면 자동으로 채워져요. 그동안 전문은 볼 수 있어요.</div>
                    </div>
                  </div>
                  <div className="bar-track" aria-hidden="true">
                    <i />
                  </div>
                </section>
                {['결론', '알게 된 것'].map((name) => (
                  <section key={name} className="d-sec" aria-hidden="true">
                    <div className="sh">{name}</div>
                    <i className="sk" style={{ width: '90%' }} />
                    <i className="sk" style={{ width: '70%' }} />
                  </section>
                ))}
              </>
            )}

            {(kind === 'failed' || kind === 'unorganized') && (
              <section
                className="banner banner-danger"
                role={kind === 'failed' ? 'alert' : 'status'}
                aria-label={kind === 'failed' ? '정리 실패' : '정리 전'}
              >
                <div className="banner-row">
                  <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
                    <path d="M12 3l10 18H2zM12 10v5M12 18h.01" />
                  </svg>
                  <div>
                    <div className="banner-title">
                      {kind === 'failed' ? '일지를 정리하지 못했어요' : '아직 일지로 정리되지 않았어요'}
                    </div>
                    <div className="banner-sub">
                      대화 내용은 그대로 남아 있어요. 다시 정리하면 요약과 노트가 만들어져요.
                    </div>
                  </div>
                </div>
                <button type="button" className="btn-danger" disabled={busy === 'retry'} onClick={() => void retry()}>
                  <Icon size={20}>
                    <path d="M20 12a8 8 0 1 1-2.5-5.8M20 4v5h-5" />
                  </Icon>
                  {busy === 'retry' ? '요청하는 중…' : '다시 정리'}
                </button>
              </section>
            )}

            {sections.conclusion && (
              <section className="d-sec d-concl" aria-label="결론">
                <div className="sh">결론</div>
                <div className="d-concl-text">
                  <InlineMarkdown text={sections.conclusion.text} />
                  <Cites numbers={sections.conclusion.cites} />
                </div>
              </section>
            )}

            {sections.findings.length > 0 && (
              <section className="d-sec" aria-label={sections.legacy ? '요약' : '알게 된 것'}>
                <div className="sh">{sections.legacy ? '요약' : '알게 된 것'}</div>
                <Lines lines={sections.findings} icon={BULLET} tone="primary" />
              </section>
            )}

            {sections.checks.length > 0 && (
              <section className="d-sec" aria-label="확인할 것">
                <div className="sh">확인할 것</div>
                <Lines
                  lines={sections.checks.map((text) => ({ text, cites: [] }))}
                  icon={QUESTION}
                  tone="amber"
                />
              </section>
            )}

            {hasNotes &&
              noteGroups.map(({ kind: noteKind, notes }) =>
                notes.length === 0 ? null : (
                  <section key={noteKind} className="d-sec" aria-label={KIND_LABEL[noteKind]}>
                    <div className="sh sh-row">
                      <span>
                        {KIND_LABEL[noteKind]} {notes.length}
                      </span>
                      {noteKind === 'idea' && <span className="sh-hint">별표를 누르면 위로 올라가요</span>}
                    </div>
                    <ul className="notes">
                      {notes.map((note) => (
                        <NoteRow
                          key={note.id}
                          note={note}
                          editable={true}
                          onPatch={(n, patch) => void patchNote(n, patch)}
                          onSave={saveNote}
                        />
                      ))}
                    </ul>
                  </section>
                ),
              )}

            {kind !== 'pending' && !hasNotes && kind === 'done' && (
              <p className="d-none">저장한 노트가 없어요.</p>
            )}

            {detail.citations.length > 0 && (
              <section className="d-sec" aria-label="인용">
                <div className="sh">인용</div>
                {detail.citations.map((citation) => (
                  <div key={citation.n} className="d-cite">
                    [{citation.n}]{' '}
                    {isSafeUrl(citation.url) ? (
                      <a href={citation.url} target="_blank" rel="noopener noreferrer">
                        {citation.title}
                      </a>
                    ) : (
                      citation.title
                    )}
                  </div>
                ))}
              </section>
            )}

            {session.tags.length > 0 && (
              <ul className="d-tags" aria-label="태그">
                {session.tags.map((tag) => (
                  <li key={tag}>#{tag}</li>
                ))}
              </ul>
            )}

            <section className="d-sec" aria-label="전문">
              <button
                type="button"
                className="t-toggle"
                aria-expanded={showTranscript}
                onClick={() => setTranscriptOpen(!showTranscript)}
              >
                <span className="t-toggle-title">전문</span>
                <span className="t-toggle-act">
                  {showTranscript ? '접기' : '전문 보기'}
                  <svg className="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true">
                    <path d={showTranscript ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} />
                  </svg>
                </span>
              </button>
              {showTranscript && <Transcript turns={detail.turns} personaName={detail.persona_name} />}
            </section>

            <div className="d-manage">
              {canReformat(detail) && (
                <button type="button" className="btn btn-flat" disabled={busy === 'retry'} onClick={() => void retry()}>
                  {busy === 'retry' ? '요청하는 중…' : '다시 정리'}
                </button>
              )}
              <button
                type="button"
                className="btn btn-flat btn-flat-danger"
                disabled={!canDelete || busy === 'delete'}
                onClick={() => setConfirmDelete(true)}
              >
                대화 지우기
              </button>
            </div>
            {!canDelete && <p className="d-none">진행 중인 대화는 끝낸 뒤 지울 수 있어요.</p>}

            {notice && (
              <p className="chat-error" role="alert">
                {notice}
              </p>
            )}
          </>
        )}
      </div>

      {session && (
        <div className="act">
          {isOpenHere ? (
            <button type="button" className="btn btn-primary btn-act" onClick={onOpenChat}>
              대화로 돌아가기
            </button>
          ) : (
            <>
              {unopenedActive && (
                <button
                  type="button"
                  className="btn btn-act"
                  disabled={busy !== null}
                  onClick={() => void endNow()}
                >
                  {busy === 'end' ? '정리하는 중…' : '대화 끝내기'}
                </button>
              )}
              <button
                type="button"
                className="btn btn-act"
                disabled={busy !== null || otherOpen}
                onClick={() => void resume('text')}
              >
                {busy === 'reopen' && openingMode === 'text' ? '여는 중…' : '글로 이어서'}
              </button>
              <button
                type="button"
                className="btn btn-primary btn-act"
                disabled={busy !== null || otherOpen}
                onClick={() => void resume('voice')}
              >
                {busy === 'reopen' && openingMode === 'voice' ? '여는 중…' : '음성으로 이어서'}
              </button>
            </>
          )}
          {otherOpen && <p className="act-hint">진행 중인 대화를 끝낸 뒤 이어서 할 수 있어요.</p>}
        </div>
      )}

      {titleOpen && (
        <div
          className="dialog-back"
          onKeyDown={(event) => event.key === 'Escape' && setTitleOpen(false)}
        >
          <div className="dialog sheet" role="dialog" aria-modal="true" aria-label="제목 수정">
            <div className="sheet-grip" aria-hidden="true" />
            <h2>제목 수정</h2>
            <label className="field-label" htmlFor="journal-title">
              대화 제목
            </label>
            <input
              id="journal-title"
              className="field"
              value={titleDraft}
              maxLength={TITLE_MAX}
              autoFocus
              onChange={(event) => setTitleDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.nativeEvent.isComposing) void saveTitle()
              }}
            />
            <div className="field-foot">
              <span>다시 정리해도 제목은 바뀌지 않아요.</span>
              <span>
                {titleDraft.length} / {TITLE_MAX}
              </span>
            </div>
            {titleError && (
              <p className="chat-error" role="alert">
                {titleError}
              </p>
            )}
            <div className="dialog-actions">
              <button type="button" className="btn" onClick={() => setTitleOpen(false)}>
                취소
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={titleSaving || !titleOf(titleDraft)}
                onClick={() => void saveTitle()}
              >
                {titleSaving ? '저장하는 중…' : '저장'}
              </button>
            </div>
          </div>
        </div>
      )}

      {confirmDelete && (
        <div
          className="dialog-back"
          onKeyDown={(event) => event.key === 'Escape' && setConfirmDelete(false)}
        >
          <div
            className="dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="del-title"
            aria-describedby="del-desc"
          >
            <h2 id="del-title">이 대화를 지울까요?</h2>
            <p id="del-desc">대화 전문과 저장한 노트가 모두 사라지고 되돌릴 수 없어요.</p>
            <div className="dialog-actions">
              <button type="button" className="btn" autoFocus onClick={() => setConfirmDelete(false)}>
                취소
              </button>
              <button type="button" className="btn-danger" onClick={() => void remove()}>
                지우기
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
