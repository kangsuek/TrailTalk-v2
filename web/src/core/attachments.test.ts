import { describe, expect, it } from 'vitest'
import {
  DEFAULT_ATTACHMENT_LIMITS as L,
  acceptOf,
  addFiles,
  attachmentKind,
  attachmentUrl,
  bubbleAttachment,
  checkFile,
  emptyTextHint,
  kindOfMime,
  limitsDetail,
  limitsNote,
  removeFile,
  type PickedFile,
} from './attachments.ts'

const keys = () => {
  let n = 0
  return () => `k${(n += 1)}`
}
const f = (name: string, size = 1000) => ({ name, size, ref: name })

describe('attachments', () => {
  it('확장자로 종류를 가른다(대소문자 무관)', () => {
    expect(attachmentKind('A.JPG', L)).toBe('image')
    expect(attachmentKind('notes.md', L)).toBe('text')
    expect(attachmentKind('약관.PDF', L)).toBe('pdf')
    expect(attachmentKind('run.exe', L)).toBeNull()
    expect(attachmentKind('noext', L)).toBeNull()
  })

  it('MIME으로 종류를 가른다', () => {
    expect(kindOfMime('image/png')).toBe('image')
    expect(kindOfMime('application/pdf')).toBe('pdf')
    expect(kindOfMime('text/plain')).toBe('text')
  })

  it('파일 하나의 형식·크기를 안내한다', () => {
    expect(checkFile({ name: 'a.png', size: 1000 }, L)).toBeNull()
    expect(checkFile({ name: 'a.exe', size: 1 }, L)).toContain('지원하지 않는')
    expect(checkFile({ name: 'a.png', size: 6 * 1024 * 1024 }, L)).toContain('5MB')
    expect(checkFile({ name: 'a.txt', size: 201 * 1024 }, L)).toContain('200KB')
    expect(checkFile({ name: 'a.pdf', size: 6 * 1024 * 1024 }, L)).toContain('PDF는 5MB')
    expect(checkFile({ name: 'a.txt', size: 0 }, L)).toContain('비어')
  })

  it('accept 값은 점을 붙인 확장자 목록이다', () => {
    expect(acceptOf(L)).toBe('.gif,.jpeg,.jpg,.png,.webp,.csv,.json,.md,.txt,.pdf')
  })

  it('고른 파일을 더하고 규칙에 안 맞는 파일은 뺀 뒤 첫 문제를 알린다', () => {
    const result = addFiles([], [f('a.png'), f('b.exe'), f('c.txt')], L, keys())
    expect(result.files.map((x) => [x.key, x.name, x.kind])).toEqual([
      ['k1', 'a.png', 'image'],
      ['k2', 'c.txt', 'text'],
    ])
    expect(result.notice).toContain('b.exe')
  })

  it('개수 한도를 넘는 파일은 먼저 담은 것을 남기고 뺀다', () => {
    const existing: PickedFile<string>[] = addFiles([], [f('1.png'), f('2.png')], L, keys()).files
    const result = addFiles(existing, [f('3.png'), f('4.png')], L, keys())
    expect(result.files.map((x) => x.name)).toEqual(['1.png', '2.png', '3.png'])
    expect(result.notice).toBe('파일은 한 번에 3개까지 보낼 수 있어요.')
  })

  it('PDF는 한 번에 한 개다', () => {
    const result = addFiles([], [f('a.pdf'), f('b.pdf')], L, keys())
    expect(result.files.map((x) => x.name)).toEqual(['a.pdf'])
    expect(result.notice).toBe('PDF는 한 번에 1개까지 보낼 수 있어요.')
  })

  it('같은 이름·크기의 파일은 두 번 담지 않고 알림도 없다', () => {
    const first = addFiles([], [f('a.png')], L, keys()).files
    const again = addFiles(first, [f('a.png')], L, keys())
    expect(again.files).toHaveLength(1)
    expect(again.notice).toBeNull()
  })

  it('파일을 뺀다', () => {
    const files = addFiles([], [f('a.png'), f('b.txt')], L, keys()).files
    expect(removeFile(files, 'k1').map((x) => x.name)).toEqual(['b.txt'])
  })

  it('안내 문구는 서버 한도 값에서 만든다', () => {
    expect(limitsNote(L)).toBe('첨부는 글과 함께 보내요 · 최대 3개')
    expect(limitsNote({ ...L, max_files: 2 })).toContain('최대 2개')
    expect(limitsDetail(L)).toBe('이미지 5MB까지, 텍스트 200KB·10,000자까지, PDF 1개 10쪽까지')
  })

  it('첨부만 있고 글이 없으면 힌트를 낸다', () => {
    expect(emptyTextHint('  ', 1)).not.toBeNull()
    expect(emptyTextHint('질문', 1)).toBeNull()
    expect(emptyTextHint('', 0)).toBeNull()
  })

  it('서버 첨부를 말풍선 첨부로 바꾼다', () => {
    expect(attachmentUrl('a b', true)).toBe('/api/attachments/a%20b?thumb=1')
    expect(
      bubbleAttachment({ id: 'x', name: 'p.png', mime: 'image/png', size: 1, thumb: true }),
    ).toEqual({
      key: 'x',
      name: 'p.png',
      kind: 'image',
      preview: '/api/attachments/x?thumb=1',
      href: '/api/attachments/x',
    })
    expect(
      bubbleAttachment({ id: 'y', name: 'a.pdf', mime: 'application/pdf', size: 1, thumb: false }),
    ).toMatchObject({ kind: 'pdf', preview: null, href: '/api/attachments/y' })
  })
})
