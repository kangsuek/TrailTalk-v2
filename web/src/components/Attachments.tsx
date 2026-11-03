import type { AttachmentKind, BubbleAttachment, PickedFile } from '../core/attachments.ts'

// 파일 첨부 화면 조각(시안 대화 09, 일지 05): 입력창의 선택 칩과 말풍선·전문의 썸네일·칩.

const ICONS: Record<AttachmentKind, string> = {
  image: 'M3 5h18v14H3zM9 10m-1.6 0a1.6 1.6 0 1 0 3.2 0a1.6 1.6 0 1 0-3.2 0M21 16l-5-5-8 8',
  text: 'M6 3h9l4 4v14H6zM14 3v5h5',
  pdf: 'M6 3h9l4 4v14H6zM14 3v5h5M9 14h6M9 17h4',
}

export function FileIcon({ kind }: { kind: AttachmentKind }) {
  return (
    <svg className="ic ic-xs" viewBox="0 0 24 24" aria-hidden="true">
      <path d={ICONS[kind]} />
    </svg>
  )
}

/** 입력창 위에 올려 둔 첨부 칩(빼기 버튼 포함) */
export function PickedChips({
  files,
  disabled,
  onRemove,
}: {
  files: readonly PickedFile[]
  disabled?: boolean
  onRemove: (key: string) => void
}) {
  if (files.length === 0) return null
  return (
    <ul className="att-picked" aria-label="보낼 첨부">
      {files.map((file) => (
        <li key={file.key} className="att-chip">
          <FileIcon kind={file.kind} />
          <span className="att-name">{file.name}</span>
          <button
            type="button"
            aria-label={`${file.name} 첨부 빼기`}
            disabled={disabled}
            onClick={() => onRemove(file.key)}
          >
            <svg className="ic ic-xs" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </li>
      ))}
    </ul>
  )
}

/** 말풍선 안의 첨부: 썸네일이 있는 이미지는 그림으로, 나머지는 파일 이름 칩으로 */
export function BubbleAttachments({ items }: { items: readonly BubbleAttachment[] }) {
  if (items.length === 0) return null
  return (
    <ul className="att-list" aria-label="첨부">
      {items.map((item) => (
        <li key={item.key} className="att-item" data-kind={item.kind}>
          {item.preview ? (
            item.href ? (
              <a
                href={item.href}
                target="_blank"
                rel="noreferrer"
                aria-label={`${item.name} 크게 보기`}
              >
                <img className="att-thumb" src={item.preview} alt={item.name} loading="lazy" />
              </a>
            ) : (
              <img className="att-thumb" src={item.preview} alt={item.name} />
            )
          ) : item.href ? (
            <a className="att-chip att-chip-in" href={item.href} target="_blank" rel="noreferrer">
              <FileIcon kind={item.kind} />
              <span className="att-name">{item.name}</span>
            </a>
          ) : (
            <span className="att-chip att-chip-in">
              <FileIcon kind={item.kind} />
              <span className="att-name">{item.name}</span>
            </span>
          )}
        </li>
      ))}
    </ul>
  )
}
