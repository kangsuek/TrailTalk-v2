import { useMemo, type ReactNode } from 'react'
import { parseInline, parseMarkdown, type Inline } from '../core/markdown.ts'

function renderInline(nodes: Inline[]): ReactNode[] {
  return nodes.map((node, index) => {
    switch (node.type) {
      case 'strong':
        return <strong key={index}>{renderInline(node.children)}</strong>
      case 'em':
        return <em key={index}>{renderInline(node.children)}</em>
      case 'code':
        return <code key={index}>{node.text}</code>
      case 'link':
        // 주소는 파서가 http·https만 통과시킨다. 새 탭에서 열고 이 앱의 정보를 넘기지 않는다
        return (
          <a key={index} href={node.href} target="_blank" rel="noopener noreferrer">
            {renderInline(node.children)}
          </a>
        )
      default:
        return node.text
    }
  })
}

/** 한 줄 안의 서식만 그린다(요약 줄·노트처럼 문단 요소가 필요 없는 자리). 줄바꿈은 그대로 둔다. */
export function InlineMarkdown({ text }: { text: string }) {
  const nodes = useMemo(() => parseInline(text), [text])
  return <>{renderInline(nodes)}</>
}

/** 마크다운 부분집합(굵게·기울임·링크·목록·인라인 코드)을 그린다. HTML 문자열을 만들지 않는다. */
export default function Markdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdown(text), [text])
  return (
    <>
      {blocks.map((block, index) => {
        if (block.type === 'paragraph') {
          return (
            <p key={index} className="md-p">
              {renderInline(block.children)}
            </p>
          )
        }
        const List = block.ordered ? 'ol' : 'ul'
        return (
          <List key={index} className="md-list">
            {block.items.map((item, i) => (
              <li key={i}>{renderInline(item)}</li>
            ))}
          </List>
        )
      })}
    </>
  )
}
