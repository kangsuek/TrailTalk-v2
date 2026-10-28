import { describe, expect, it } from 'vitest'
import { joinSentences, parseInline, parseMarkdown, type Inline } from './markdown.ts'

const t = (text: string): Inline => ({ type: 'text', text })

describe('parseInline', () => {
  it('굵게·기울임·인라인 코드를 읽는다', () => {
    expect(parseInline('**굵게** 그리고 *기울임* 그리고 `code`')).toEqual([
      { type: 'strong', children: [t('굵게')] },
      t(' 그리고 '),
      { type: 'em', children: [t('기울임')] },
      t(' 그리고 '),
      { type: 'code', text: 'code' },
    ])
  })

  it('밑줄 표시와 굵게 속 기울임도 읽는다', () => {
    expect(parseInline('__굵게__ _기울임_')).toEqual([
      { type: 'strong', children: [t('굵게')] },
      t(' '),
      { type: 'em', children: [t('기울임')] },
    ])
    expect(parseInline('**굵게 *속* 끝**')).toEqual([
      { type: 'strong', children: [t('굵게 '), { type: 'em', children: [t('속')] }, t(' 끝')] },
    ])
  })

  it('짝이 없거나 공백에 붙은 표시는 글자로 둔다', () => {
    expect(parseInline('2 * 3 = 6, 4 * 5')).toEqual([t('2 * 3 = 6, 4 * 5')])
    expect(parseInline('**닫히지 않음')).toEqual([t('**닫히지 않음')])
    expect(parseInline('snake_case_name')).toEqual([t('snake_case_name')])
    expect(parseInline('`닫히지 않음')).toEqual([t('`닫히지 않음')])
  })

  it('코드 안의 서식 표시는 해석하지 않는다', () => {
    expect(parseInline('`**x**` 와 **`y`**')).toEqual([
      { type: 'code', text: '**x**' },
      t(' 와 '),
      { type: 'strong', children: [{ type: 'code', text: 'y' }] },
    ])
  })

  it('http·https 링크만 링크로 만든다', () => {
    expect(parseInline('[문서](https://example.com/a?b=1) 보기')).toEqual([
      { type: 'link', href: 'https://example.com/a?b=1', children: [t('문서')] },
      t(' 보기'),
    ])
    expect(parseInline('[문서](http://example.com)')[0]).toMatchObject({ type: 'link' })
  })

  it('다른 스킴과 깨진 링크는 쓴 그대로 글자로 남는다', () => {
    for (const source of [
      '[눌러](javascript:alert(1))',
      '[눌러](JAVASCRIPT:alert(1))',
      '[눌러](data:text/html,x)',
      '[눌러](//evil.example.com)',
      '[눌러](ftp://example.com)',
      '[눌러]( https://a.com b)',
      '[](https://example.com)',
      '[링크만',
    ]) {
      expect(parseInline(source).every((node) => node.type !== 'link')).toBe(true)
    }
    expect(parseInline('[눌러](data:text/html,x)')).toEqual([t('[눌러](data:text/html,x)')])
  })

  it('겹친 대괄호는 바깥을 글자로 두고 안쪽만 링크로 읽는다', () => {
    const nodes = parseInline('[[안](https://b.com)](https://a.com)')
    const links = nodes.filter((node) => node.type === 'link')
    expect(links).toEqual([{ type: 'link', href: 'https://b.com', children: [t('안')] }])
  })

  it('원시 HTML은 해석하지 않고 글자로 둔다', () => {
    expect(parseInline('<script>alert(1)</script> <b>굵게</b>')).toEqual([
      t('<script>alert(1)</script> <b>굵게</b>'),
    ])
    expect(parseInline('<img src=x onerror=alert(1)>')).toEqual([
      t('<img src=x onerror=alert(1)>'),
    ])
  })

  it('역슬래시로 서식 표시를 글자로 쓴다', () => {
    expect(parseInline('\\*별표\\* \\[대괄호\\]')).toEqual([t('*별표* [대괄호]')])
  })
})

describe('parseMarkdown', () => {
  it('빈 줄로 문단을 나누고 문단 안 줄바꿈은 둔다', () => {
    expect(parseMarkdown('첫째 줄\n둘째 줄\n\n다음 문단')).toEqual([
      { type: 'paragraph', children: [t('첫째 줄\n둘째 줄')] },
      { type: 'paragraph', children: [t('다음 문단')] },
    ])
  })

  it('순서 없는 목록과 순서 있는 목록을 읽는다', () => {
    expect(parseMarkdown('- 하나\n* 둘\n+ **셋**')).toEqual([
      {
        type: 'list',
        ordered: false,
        items: [[t('하나')], [t('둘')], [{ type: 'strong', children: [t('셋')] }]],
      },
    ])
    expect(parseMarkdown('1. 하나\n2) 둘')).toEqual([
      { type: 'list', ordered: true, items: [[t('하나')], [t('둘')]] },
    ])
  })

  it('목록 앞뒤의 문단과 종류가 바뀌는 목록을 나눈다', () => {
    const blocks = parseMarkdown('소개\n- 가\n1. 나\n마무리')
    expect(blocks.map((b) => b.type)).toEqual(['paragraph', 'list', 'list', 'paragraph'])
    expect(blocks[1]).toMatchObject({ ordered: false })
    expect(blocks[2]).toMatchObject({ ordered: true })
  })

  it('들여 쓴 줄은 앞 목록 항목에 이어 붙인다', () => {
    expect(parseMarkdown('- 항목\n  이어지는 줄')).toEqual([
      { type: 'list', ordered: false, items: [[t('항목\n이어지는 줄')]] },
    ])
  })

  it('굵게 시작이나 소수는 목록이 아니다', () => {
    expect(parseMarkdown('**굵게** 시작')[0]).toMatchObject({ type: 'paragraph' })
    expect(parseMarkdown('1.5배 빨라요')[0]).toMatchObject({ type: 'paragraph' })
    expect(parseMarkdown('-5도예요')[0]).toMatchObject({ type: 'paragraph' })
  })

  it('제목·표·인용 문법은 글자로 남고 빈 글은 블록이 없다', () => {
    expect(parseMarkdown('# 제목')).toEqual([{ type: 'paragraph', children: [t('# 제목')] }])
    expect(parseMarkdown('> 인용')).toEqual([{ type: 'paragraph', children: [t('> 인용')] }])
    expect(parseMarkdown('  \n\n ')).toEqual([])
  })
})

describe('joinSentences', () => {
  it('문장은 한 칸으로 잇고 목록 표시 앞에서만 줄을 바꾼다', () => {
    expect(joinSentences(['첫 문장이에요.', '둘째 문장이에요.'])).toBe(
      '첫 문장이에요. 둘째 문장이에요.',
    )
    expect(joinSentences(['세 가지예요.', '- 하나', '- 둘', '1. 셋', '끝이에요.'])).toBe(
      '세 가지예요.\n- 하나\n- 둘\n1. 셋 끝이에요.',
    )
  })

  it('소수·번호 없는 숫자로 시작하는 문장은 목록으로 보지 않는다', () => {
    expect(joinSentences(['가격은요.', '1.5배 올랐어요.'])).toBe('가격은요. 1.5배 올랐어요.')
  })

  it('빈 목록은 빈 글이다', () => {
    expect(joinSentences([])).toBe('')
  })
})
