// 파일 첨부(client-contract 2.13) 보내기 전 안내. 한도의 정본은 서버이고(GET /api/profile의
// client.attachments), 여기서는 안내용으로만 판정한다(서버가 다시 검증한다). File 같은 브라우저
// 객체에 기대지 않고 이름·크기만 본다. PDF 쪽수·텍스트 글자 수·세션 누적 한도는 파일을 열어야 알 수
// 있으므로 서버가 판정하고, 여기서는 안내 문구에 한도만 보인다.

import type { Attachment } from './journal.ts'

export interface AttachmentLimits {
  max_files: number
  image_upload_max_bytes: number
  image_max_px: number
  text_max_bytes: number
  text_max_chars: number
  session_max_images: number
  session_max_text_chars: number
  max_pdfs: number
  pdf_max_bytes: number
  pdf_max_pages: number
  session_max_pdf_pages: number
  image_extensions: string[]
  text_extensions: string[]
  pdf_extensions: string[]
}

/** 프로필을 받기 전(또는 받지 못했을 때)의 대체값. 서버 기본 설정과 같다 */
export const DEFAULT_ATTACHMENT_LIMITS: AttachmentLimits = {
  max_files: 3,
  image_upload_max_bytes: 5 * 1024 * 1024,
  image_max_px: 1024,
  text_max_bytes: 200 * 1024,
  text_max_chars: 10_000,
  session_max_images: 10,
  session_max_text_chars: 30_000,
  max_pdfs: 1,
  pdf_max_bytes: 5 * 1024 * 1024,
  pdf_max_pages: 10,
  session_max_pdf_pages: 20,
  image_extensions: ['gif', 'jpeg', 'jpg', 'png', 'webp'],
  text_extensions: ['csv', 'json', 'md', 'txt'],
  pdf_extensions: ['pdf'],
}

export type AttachmentKind = 'image' | 'text' | 'pdf'

export interface FileInfo {
  name: string
  size: number
}

/** 입력창에 올려 둔 파일. ref는 화면이 쓰는 원본(File)이며 이 모듈은 열어 보지 않는다 */
export interface PickedFile<T = unknown> extends FileInfo {
  key: string
  kind: AttachmentKind
  ref: T
}

function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.')
  return dot < 0 ? '' : name.slice(dot + 1).toLowerCase()
}

export function attachmentKind(name: string, limits: AttachmentLimits): AttachmentKind | null {
  const ext = extensionOf(name)
  if (limits.image_extensions.includes(ext)) return 'image'
  if (limits.text_extensions.includes(ext)) return 'text'
  if (limits.pdf_extensions.includes(ext)) return 'pdf'
  return null
}

/** 서버가 준 MIME으로 종류를 가른다(이미지·PDF가 아니면 텍스트) */
export function kindOfMime(mime: string): AttachmentKind {
  if (mime.startsWith('image/')) return 'image'
  if (mime === 'application/pdf') return 'pdf'
  return 'text'
}

/** 파일 선택 창에 넘길 accept 값(".png,.jpg,…") */
export function acceptOf(limits: AttachmentLimits): string {
  return [...limits.image_extensions, ...limits.text_extensions, ...limits.pdf_extensions]
    .map((ext) => `.${ext}`)
    .join(',')
}

function megabytes(bytes: number): string {
  return `${Math.floor(bytes / (1024 * 1024))}MB`
}

/** 파일 하나가 한도 안인지. 문제가 있으면 한글 안내를, 괜찮으면 null */
export function checkFile(file: FileInfo, limits: AttachmentLimits): string | null {
  const kind = attachmentKind(file.name, limits)
  if (kind === null) {
    return `${file.name}: 지원하지 않는 형식이에요(이미지, 텍스트 ${limits.text_extensions.join('·')}, PDF만 돼요).`
  }
  if (file.size <= 0) return `${file.name}: 비어 있는 파일이에요.`
  if (kind === 'image' && file.size > limits.image_upload_max_bytes) {
    return `${file.name}: 이미지는 ${megabytes(limits.image_upload_max_bytes)}까지 보낼 수 있어요.`
  }
  if (kind === 'pdf' && file.size > limits.pdf_max_bytes) {
    return `${file.name}: PDF는 ${megabytes(limits.pdf_max_bytes)}까지 보낼 수 있어요.`
  }
  if (kind === 'text' && file.size > limits.text_max_bytes) {
    return `${file.name}: 텍스트 파일은 ${Math.floor(limits.text_max_bytes / 1024)}KB까지 보낼 수 있어요.`
  }
  return null
}

export interface AddResult<T> {
  files: PickedFile<T>[]
  /** 걸러낸 파일이 있을 때의 안내(첫 문제) */
  notice: string | null
}

/**
 * 고른 파일을 목록에 더한다. 형식·크기가 안 맞거나 개수·PDF 수 한도를 넘는 파일은 빼고
 * (먼저 담은 것이 우선) 첫 문제를 안내로 돌려준다. 같은 이름·크기 파일은 두 번 담지 않는다.
 */
export function addFiles<T>(
  existing: readonly PickedFile<T>[],
  incoming: readonly { name: string; size: number; ref: T }[],
  limits: AttachmentLimits,
  nextKey: () => string,
): AddResult<T> {
  const files = [...existing]
  let notice: string | null = null
  const reject = (message: string) => {
    notice ??= message
  }
  for (const file of incoming) {
    const kind = attachmentKind(file.name, limits)
    const problem = checkFile(file, limits)
    if (problem || kind === null) {
      reject(problem ?? '')
      continue
    }
    if (files.some((f) => f.name === file.name && f.size === file.size)) continue
    if (files.length >= limits.max_files) {
      reject(`파일은 한 번에 ${limits.max_files}개까지 보낼 수 있어요.`)
      continue
    }
    if (kind === 'pdf' && files.filter((f) => f.kind === 'pdf').length >= limits.max_pdfs) {
      reject(`PDF는 한 번에 ${limits.max_pdfs}개까지 보낼 수 있어요.`)
      continue
    }
    files.push({ key: nextKey(), name: file.name, size: file.size, kind, ref: file.ref })
  }
  return { files, notice }
}

export function removeFile<T>(files: readonly PickedFile<T>[], key: string): PickedFile<T>[] {
  return files.filter((f) => f.key !== key)
}

/** 입력창 아래에 늘 보이는 한도 안내 */
export function limitsNote(limits: AttachmentLimits): string {
  return `첨부는 글과 함께 보내요 · 최대 ${limits.max_files}개`
}

/** 자세한 한도(안내 글 아래 보조 설명이나 title에 쓴다) */
export function limitsDetail(limits: AttachmentLimits): string {
  return (
    `이미지 ${megabytes(limits.image_upload_max_bytes)}까지, ` +
    `텍스트 ${Math.floor(limits.text_max_bytes / 1024)}KB·${limits.text_max_chars.toLocaleString('en-US')}자까지, ` +
    `PDF ${limits.max_pdfs}개 ${limits.pdf_max_pages}쪽까지`
  )
}

/** 글이 비어 있으면 보낼 수 없다(기본 질문을 넣지 않는다). 첨부가 있는데 글이 없을 때의 안내 */
export function emptyTextHint(text: string, fileCount: number): string | null {
  return fileCount > 0 && !text.trim() ? '파일과 함께 보낼 글을 적어 주세요.' : null
}

/** 첨부 오류 코드(SSE 전 JSON 오류)인가. 쓴 글과 첨부 목록을 입력창에 되돌릴 때 구분한다 */
export const isAttachmentError = (code: string | undefined): boolean =>
  code !== undefined && code.startsWith('attachment_')

/** 서버에 있는 첨부의 주소(썸네일은 이미지만) */
export function attachmentUrl(id: string, thumb = false): string {
  return `/api/attachments/${encodeURIComponent(id)}${thumb ? '?thumb=1' : ''}`
}

/** 말풍선에 보일 첨부 */
export interface BubbleAttachment {
  key: string
  name: string
  kind: AttachmentKind
  /** 이미지 미리보기 주소(서버 썸네일이나 방금 고른 파일의 임시 주소). 없으면 칩으로 보인다 */
  preview: string | null
  /** 내려받기·원본 보기 주소(방금 보낸 것은 서버 ID를 몰라 null) */
  href: string | null
}

/** 서버가 내려준 첨부(전문·다시 열기)를 말풍선 첨부로 */
export function bubbleAttachment(attachment: Attachment): BubbleAttachment {
  const kind = kindOfMime(attachment.mime)
  return {
    key: attachment.id,
    name: attachment.name,
    kind,
    preview: kind === 'image' && attachment.thumb ? attachmentUrl(attachment.id, true) : null,
    href: attachmentUrl(attachment.id),
  }
}
