import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/http.ts'
import { deleteJournal, listJournal, retryJournal } from '../api/journal.ts'
import {
  TITLE_FALLBACK,
  cardKind,
  countPills,
  groupByDate,
  hasPending,
  isDeletable,
  metaLine,
  previewOf,
  type JournalItem,
} from '../core/journal.ts'
import { usePendingPoll } from '../hooks/usePendingPoll.ts'

interface Props {
  /** 일지 상세를 연다 */
  onOpen: (id: string) => void
  /** 지금 이 화면에서 열려 있는 대화로 돌아간다 */
  onOpenChat: () => void
  /** 이 앱(대화 화면)이 지금 들고 있는 진행 중 대화. 그 밖의 진행 중 대화는 상세에서 이어받는다 */
  activeSessionId: string | null
}

const errorText = (error: unknown): string =>
  error instanceof ApiError ? error.message : '문제가 생겼어요. 다시 해 주세요.'

function Pills({ item }: { item: JournalItem }) {
  const pills = countPills(item.counts)
  if (pills.length === 0) return null
  return (
    <span className="j-pills">
      {pills.map((pill) => (
        <span key={pill.kind} className={`pill pill-${pill.kind}`}>
          {pill.text}
        </span>
      ))}
    </span>
  )
}

function Spinner() {
  return (
    <svg className="ic ic-sm j-spin" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3a9 9 0 1 0 9 9" />
    </svg>
  )
}

/** 카드 안쪽(선택 모드와 보통 모드가 같이 쓴다). */
function CardBody({ item }: { item: JournalItem }) {
  const kind = cardKind(item)
  const preview = kind === 'done' ? previewOf(item) : null
  return (
    <>
      <span className="j-meta">{metaLine(item)}</span>
      <span className="j-title">{item.title ?? TITLE_FALLBACK}</span>
      {preview && <span className="j-preview">{preview}</span>}
      {kind === 'done' && <Pills item={item} />}
      {kind === 'pending' && (
        <span className="j-note j-note-amber">
          <Spinner />
          일지를 정리하고 있어요
        </span>
      )}
      {kind === 'active' && (
        <span className="j-foot">
          <span className="pill pill-live">
            <i className="dot" aria-hidden="true" />
            대화 중
          </span>
          <span className="j-link">
            대화로 돌아가기
            <svg className="ic ic-sm" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M9 6l6 6-6 6" />
            </svg>
          </span>
        </span>
      )}
    </>
  )
}

export default function JournalListScreen({ onOpen, onOpenChat, activeSessionId }: Props) {
  const [items, setItems] = useState<JournalItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [selecting, setSelecting] = useState(false)
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set())
  const [confirming, setConfirming] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [retrying, setRetrying] = useState<ReadonlySet<string>>(new Set())
  const aborter = useRef<AbortController | null>(null)

  const load = useCallback(async (silent: boolean) => {
    aborter.current?.abort()
    const controller = (aborter.current = new AbortController())
    try {
      const next = await listJournal(controller.signal)
      setItems(next)
      setError(null)
    } catch (caught) {
      if (controller.signal.aborted) return
      if (!silent) setError(errorText(caught)) // 정리 중 자동 갱신 실패는 조용히 넘어간다
    }
  }, [])

  useEffect(() => {
    void load(false)
    return () => aborter.current?.abort()
  }, [load])

  usePendingPoll(items !== null && hasPending(items), () => void load(true))

  function openItem(item: JournalItem) {
    if (cardKind(item) === 'active' && item.id === activeSessionId) onOpenChat()
    else onOpen(item.id)
  }

  async function retry(item: JournalItem) {
    setRetrying((current) => new Set(current).add(item.id))
    setNotice(null)
    try {
      const next = await retryJournal(item.id)
      setItems((current) => current?.map((i) => (i.id === next.id ? next : i)) ?? current)
    } catch (caught) {
      setNotice(errorText(caught))
    } finally {
      setRetrying((current) => {
        const rest = new Set(current)
        rest.delete(item.id)
        return rest
      })
    }
  }

  function stopSelecting() {
    setSelecting(false)
    setSelected(new Set())
    setConfirming(false)
    setNotice(null)
  }

  function toggle(item: JournalItem) {
    if (!isDeletable(item)) return
    setSelected((current) => {
      const next = new Set(current)
      if (!next.delete(item.id)) next.add(item.id)
      return next
    })
  }

  const deletable = (items ?? []).filter(isDeletable)
  const allSelected = deletable.length > 0 && deletable.every((item) => selected.has(item.id))

  // 고른 항목마다 차례로 지운다(동시에 보내지 않는다). 404는 이미 지워진 것으로 보고, 실패한 항목만
  // 선택된 채 남긴다(client-contract 3.2)
  async function deleteSelected() {
    setConfirming(false)
    setDeleting(true)
    setNotice(null)
    const gone = new Set<string>()
    const kept = new Set<string>()
    let failure: unknown = null
    for (const item of items ?? []) {
      if (!selected.has(item.id)) continue
      try {
        await deleteJournal(item.id)
        gone.add(item.id)
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 404) gone.add(item.id)
        else {
          kept.add(item.id)
          failure ??= caught
        }
      }
    }
    setItems((current) => current?.filter((item) => !gone.has(item.id)) ?? current)
    setSelected(kept)
    setDeleting(false)
    if (kept.size > 0) {
      const reason =
        failure instanceof ApiError && failure.code === 'session_active'
          ? '진행 중인 대화는 끝낸 뒤 지울 수 있어요.'
          : errorText(failure)
      setNotice(`${kept.size}개를 지우지 못했어요. ${reason}`)
    } else {
      stopSelecting()
    }
  }

  const groups = groupByDate(items ?? [])
  const header = selecting ? (
    <header className="hd2">
      <button type="button" className="tbtn tbtn-plain" onClick={stopSelecting}>
        취소
      </button>
      <h1 className="ttl ttl-sm">{selected.size > 0 ? `${selected.size}개 선택됨` : '항목 선택'}</h1>
      <button
        type="button"
        className="tbtn"
        disabled={deletable.length === 0}
        onClick={() =>
          setSelected(allSelected ? new Set() : new Set(deletable.map((item) => item.id)))
        }
      >
        {allSelected ? '선택 해제' : '전체 선택'}
      </button>
    </header>
  ) : (
    <header className="hd2">
      <h1 className="ttl">일지</h1>
      <button
        type="button"
        className="tbtn"
        disabled={!items || items.length === 0}
        onClick={() => setSelecting(true)}
      >
        선택
      </button>
    </header>
  )

  return (
    <section className="journal" aria-label="일지 목록">
      {header}
      <div className="j-list">
        {items === null && !error && <p className="j-empty">불러오는 중…</p>}
        {error && (
          <div className="j-empty" role="alert">
            <p>{error}</p>
            <button type="button" className="btn" onClick={() => void load(false)}>
              다시 불러오기
            </button>
          </div>
        )}
        {items && items.length === 0 && (
          <p className="j-empty">
            아직 일지가 없어요. 대화를 끝내면 여기에 쌓여요.
          </p>
        )}
        {groups.map((group) => (
          <div key={group.date} className="j-group" role="group" aria-label={group.label}>
            <h2 className="j-date">{group.label}</h2>
            {group.items.map((item) => {
              const kind = cardKind(item)
              if (selecting) {
                const ok = isDeletable(item)
                const on = selected.has(item.id)
                return (
                  <button
                    key={item.id}
                    type="button"
                    role="checkbox"
                    aria-checked={on}
                    disabled={!ok || deleting}
                    className="j-row"
                    onClick={() => toggle(item)}
                  >
                    <span className="cb" data-on={on} aria-hidden="true">
                      {on && (
                        <svg className="ic ic-check" viewBox="0 0 24 24">
                          <path d="M5 12l4 4 10-10" />
                        </svg>
                      )}
                    </span>
                    <span className="jcard" data-selected={on} data-kind={kind}>
                      <CardBody item={item} />
                      {!ok && <span className="j-note j-note-amber">진행 중이라 지울 수 없어요</span>}
                    </span>
                  </button>
                )
              }
              if (kind === 'failed' || kind === 'unorganized') {
                return (
                  <div key={item.id} className="jcard" data-kind={kind}>
                    <button type="button" className="j-main" onClick={() => openItem(item)}>
                      <span className="j-meta">{metaLine(item)}</span>
                      <span className="j-title">{item.title ?? TITLE_FALLBACK}</span>
                    </button>
                    <span className="j-foot">
                      <span className={`pill ${kind === 'failed' ? 'pill-fail' : 'pill-memo'}`}>
                        {kind === 'failed' ? '정리 실패' : '정리 전'}
                      </span>
                      <button
                        type="button"
                        className="btn-retry"
                        disabled={retrying.has(item.id)}
                        onClick={() => void retry(item)}
                      >
                        {retrying.has(item.id) ? '요청하는 중…' : kind === 'failed' ? '다시 정리' : '정리하기'}
                      </button>
                    </span>
                  </div>
                )
              }
              return (
                <button
                  key={item.id}
                  type="button"
                  className="jcard jcard-btn"
                  data-kind={kind}
                  onClick={() => openItem(item)}
                >
                  <CardBody item={item} />
                </button>
              )
            })}
          </div>
        ))}
        {notice && (
          <p className="chat-error" role="alert">
            {notice}
          </p>
        )}
      </div>

      {selecting && selected.size > 0 && (
        <div className="j-bar">
          <button
            type="button"
            className="btn-danger"
            disabled={deleting}
            onClick={() => setConfirming(true)}
          >
            <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6" />
            </svg>
            {deleting ? '지우는 중…' : `${selected.size}개 지우기`}
          </button>
        </div>
      )}

      {confirming && (
        <div className="dialog-back">
          <div
            className="dialog"
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="del-title"
            aria-describedby="del-desc"
          >
            <h2 id="del-title">{selected.size}개 대화를 지울까요?</h2>
            <p id="del-desc">대화 전문과 저장한 노트가 모두 사라지고 되돌릴 수 없어요.</p>
            <div className="dialog-actions">
              <button type="button" className="btn" autoFocus onClick={() => setConfirming(false)}>
                취소
              </button>
              <button type="button" className="btn-danger" onClick={() => void deleteSelected()}>
                지우기
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
