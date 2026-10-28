// 마크다운 부분집합 파서(docs/Spec.md 5.4): 굵게·기울임·링크·목록·인라인 코드만 읽는다.
// 원시 HTML은 해석하지 않고 글자 그대로 둔다(렌더러가 글자로만 그린다). 링크는 http·https만
// 링크가 되고 그 밖의 스킴은 쓴 그대로 글자로 남는다. UI·브라우저 API에 의존하지 않는다.

export type Inline =
  | { type: 'text'; text: string }
  | { type: 'strong'; children: Inline[] }
  | { type: 'em'; children: Inline[] }
  | { type: 'code'; text: string }
  | { type: 'link'; href: string; children: Inline[] }

export type Block =
  | { type: 'paragraph'; children: Inline[] }
  | { type: 'list'; ordered: boolean; items: Inline[][] }

const SAFE_URL = /^https?:\/\/[^\s<>"]+$/i
const ESCAPABLE = '\\`*_[]()'
const WORD_CHAR = /[\p{L}\p{N}]/u

function isWord(char: string | undefined): boolean {
  return char !== undefined && WORD_CHAR.test(char)
}

function isSpace(char: string | undefined): boolean {
  return char === undefined || /\s/.test(char)
}

/** from부터 닫는 표시(mark)를 찾는다. 코드 span 안은 건너뛰고, 못 찾으면 -1. */
function findClose(src: string, mark: string, from: number): number {
  const ch = mark[0]
  for (let j = from; j < src.length; j += 1) {
    if (src[j] === '\\') {
      j += 1
      continue
    }
    if (src[j] === '`') {
      const end = src.indexOf('`', j + 1)
      if (end === -1) continue
      j = end
      continue
    }
    if (!src.startsWith(mark, j)) continue
    if (mark.length === 1 && (src[j + 1] === ch || src[j - 1] === ch)) continue // **의 일부
    if (isSpace(src[j - 1])) continue // 닫는 표시 앞은 공백이 아니어야 한다
    if (ch === '_' && isWord(src[j + mark.length])) continue // snake_case 속 밑줄
    return j
  }
  return -1
}

/** [글자](주소)를 읽는다. 읽을 수 있으면 [노드 또는 null(링크가 아님), 다음 위치]. */
function readLink(src: string, at: number): [Inline | null, number] | null {
  const close = findBracketEnd(src, at)
  if (close === -1 || src[close + 1] !== '(') return null
  const end = src.indexOf(')', close + 2)
  if (end === -1) return null
  const label = src.slice(at + 1, close)
  const href = src.slice(close + 2, end).trim()
  if (!SAFE_URL.test(href) || !label.trim()) return [null, end + 1]
  return [{ type: 'link', href, children: parseInline(label) }, end + 1]
}

function findBracketEnd(src: string, at: number): number {
  for (let j = at + 1; j < src.length; j += 1) {
    if (src[j] === '\\') j += 1
    else if (src[j] === '[') return -1 // 겹친 대괄호는 링크로 읽지 않는다
    else if (src[j] === ']') return j
  }
  return -1
}

/** 한 줄 안의 서식을 읽는다. */
export function parseInline(src: string): Inline[] {
  const out: Inline[] = []
  let text = ''
  const flush = () => {
    if (text) out.push({ type: 'text', text })
    text = ''
  }
  let i = 0
  while (i < src.length) {
    const ch = src[i]
    if (ch === '\\' && i + 1 < src.length && ESCAPABLE.includes(src[i + 1])) {
      text += src[i + 1]
      i += 2
      continue
    }
    if (ch === '`') {
      const end = src.indexOf('`', i + 1)
      if (end > i + 1) {
        flush()
        out.push({ type: 'code', text: src.slice(i + 1, end) })
        i = end + 1
        continue
      }
    }
    if (ch === '[') {
      const link = readLink(src, i)
      if (link) {
        const [node, next] = link
        if (node) {
          flush()
          out.push(node)
        } else {
          text += src.slice(i, next) // 안전하지 않은 주소: 쓴 그대로 글자로
        }
        i = next
        continue
      }
    }
    if (ch === '*' || ch === '_') {
      const mark = src.startsWith(ch + ch, i) ? ch + ch : ch
      const bodyStart = i + mark.length
      const opensWord = ch === '_' && isWord(src[i - 1]) // snake_case 속 밑줄은 서식이 아니다
      if (!opensWord && !isSpace(src[bodyStart])) {
        const end = findClose(src, mark, bodyStart)
        if (end > bodyStart) {
          flush()
          const children = parseInline(src.slice(bodyStart, end))
          out.push({ type: mark.length === 2 ? 'strong' : 'em', children })
          i = end + mark.length
          continue
        }
      }
    }
    text += ch
    i += 1
  }
  flush()
  return out
}

/** 서식 표시를 뺀 글자만(목록 미리보기처럼 링크·굵게를 쓸 수 없는 자리). */
export function plainText(src: string): string {
  const flat = (nodes: Inline[]): string =>
    nodes
      .map((node) => (node.type === 'text' || node.type === 'code' ? node.text : flat(node.children)))
      .join('')
  return flat(parseInline(src))
}

const BULLET = /^\s{0,3}[-*+]\s+(.*)$/
const ORDERED = /^\s{0,3}\d{1,3}[.)]\s+(.*)$/

/** 줄 단위로 문단과 목록으로 나눈다. 제목·표·인용 같은 그 밖의 문법은 문단 글자로 남는다. */
export function parseMarkdown(src: string): Block[] {
  const blocks: Block[] = []
  let paragraph: string[] = []
  let list: { ordered: boolean; items: string[] } | null = null
  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push({ type: 'paragraph', children: parseInline(paragraph.join('\n')) })
    }
    paragraph = []
  }
  const flushList = () => {
    if (list) {
      blocks.push({
        type: 'list',
        ordered: list.ordered,
        items: list.items.map((item) => parseInline(item)),
      })
    }
    list = null
  }
  for (const line of src.replace(/\r\n?/g, '\n').split('\n')) {
    if (!line.trim()) {
      flushParagraph()
      flushList()
      continue
    }
    const bullet = BULLET.exec(line)
    const ordered = bullet ? null : ORDERED.exec(line)
    const item = bullet ?? ordered
    if (item) {
      flushParagraph()
      const isOrdered = ordered !== null
      if (list && list.ordered !== isOrdered) flushList()
      list ??= { ordered: isOrdered, items: [] }
      list.items.push(item[1])
      continue
    }
    if (list && /^\s{2,}\S/.test(line)) {
      list.items[list.items.length - 1] += `\n${line.trim()}` // 목록 항목의 이어지는 줄
      continue
    }
    flushList()
    paragraph.push(line)
  }
  flushParagraph()
  flushList()
  return blocks
}

const LIST_START = /^(?:[-*+]|\d{1,3}[.)])\s+/

/**
 * 서버가 나눈 문장(sentence 이벤트)을 말풍선 글로 잇는다. 서버는 문장을 줄바꿈 없이 다듬어 보내므로
 * 보통 한 칸으로 잇고, 목록 표시(- · 1.)로 시작하는 문장 앞에서만 줄을 바꿔 목록이 살아 있게 한다.
 */
export function joinSentences(sentences: readonly string[]): string {
  let out = ''
  sentences.forEach((sentence, index) => {
    if (index > 0) out += LIST_START.test(sentence) ? '\n' : ' '
    out += sentence
  })
  return out
}
