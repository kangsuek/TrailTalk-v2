import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import Markdown from './Markdown.tsx'

afterEach(cleanup)

describe('Markdown', () => {
  it('서식과 목록을 요소로 그린다', () => {
    const { container } = render(
      <Markdown text={'**굵게** *기울임* `코드`\n\n- 하나\n- 둘\n\n1. 가\n2. 나'} />,
    )
    expect(container.querySelector('strong')?.textContent).toBe('굵게')
    expect(container.querySelector('em')?.textContent).toBe('기울임')
    expect(container.querySelector('code')?.textContent).toBe('코드')
    expect(container.querySelectorAll('ul > li')).toHaveLength(2)
    expect(container.querySelectorAll('ol > li')).toHaveLength(2)
  })

  it('http 링크는 새 탭에서 열고 opener를 넘기지 않는다', () => {
    render(<Markdown text="[문서](https://example.com/a)" />)
    const link = screen.getByRole('link', { name: '문서' })
    expect(link).toHaveAttribute('href', 'https://example.com/a')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  })

  it('javascript 링크와 원시 HTML은 글자로만 보인다', () => {
    const { container } = render(
      <Markdown text={'[눌러](javascript:alert(1))\n\n<img src=x onerror=alert(1)> <b>굵게</b>'} />,
    )
    expect(screen.queryByRole('link')).toBeNull()
    expect(container.querySelector('img')).toBeNull()
    expect(container.querySelector('b')).toBeNull()
    expect(container.textContent).toContain('[눌러](javascript:alert(1))')
    expect(container.textContent).toContain('<img src=x onerror=alert(1)> <b>굵게</b>')
  })
})
