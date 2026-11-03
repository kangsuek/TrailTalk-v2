import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { messagesFromTurns } from '../core/conversation.ts'
import type { Attachment, Turn } from '../core/journal.ts'
import Transcript from './Transcript.tsx'

afterEach(cleanup)

const turn = (
  id: string,
  role: Turn['role'],
  text: string,
  attachments: Attachment[] = [],
): Turn => ({
  id,
  seq: 0,
  role,
  text,
  interrupted: false,
  merged_from: null,
  created_at: '2026-11-03T00:00:00Z',
  attachments,
})

const IMAGE: Attachment = {
  id: 'a1',
  name: 'trail-map.jpg',
  mime: 'image/jpeg',
  size: 10,
  thumb: true,
}
const TEXT: Attachment = {
  id: 'a2',
  name: '코스-메모.txt',
  mime: 'text/plain',
  size: 10,
  thumb: false,
}
const PDF: Attachment = {
  id: 'a3',
  name: '지도.pdf',
  mime: 'application/pdf',
  size: 10,
  thumb: false,
}

describe('Transcript 첨부', () => {
  it('이미지는 서버 썸네일로, 텍스트·PDF는 내려받는 칩으로 보인다', () => {
    render(
      <Transcript
        personaName="제니"
        turns={[
          turn('t1', 'user', '이 지도 봐줘', [IMAGE, TEXT, PDF]),
          turn('t2', 'assistant', '네'),
        ]}
      />,
    )
    const list = screen.getByRole('list', { name: '첨부' })
    const img = within(list).getByAltText('trail-map.jpg')
    expect(img).toHaveAttribute('src', '/api/attachments/a1?thumb=1')
    expect(img.closest('a')).toHaveAttribute('href', '/api/attachments/a1')
    expect(within(list).getByRole('link', { name: /코스-메모\.txt/ })).toHaveAttribute(
      'href',
      '/api/attachments/a2',
    )
    expect(within(list).getByRole('link', { name: /지도\.pdf/ })).toHaveAttribute(
      'href',
      '/api/attachments/a3',
    )
    expect(screen.getByText('이 지도 봐줘')).toBeInTheDocument()
  })

  it('썸네일이 없는 이미지는 칩으로 보인다', () => {
    render(
      <Transcript
        personaName="제니"
        turns={[turn('t1', 'user', '봐줘', [{ ...IMAGE, thumb: false }])]}
      />,
    )
    expect(screen.queryByRole('img')).toBeNull()
    expect(screen.getByRole('link', { name: /trail-map\.jpg/ })).toBeInTheDocument()
  })

  it('첨부가 없으면 목록을 그리지 않는다', () => {
    render(<Transcript personaName="제니" turns={[turn('t1', 'user', '안녕')]} />)
    expect(screen.queryByRole('list', { name: '첨부' })).toBeNull()
  })
})

describe('messagesFromTurns 첨부', () => {
  it('다시 연 대화의 내 말풍선에 서버 첨부가 붙는다', () => {
    const [mine, bot] = messagesFromTurns([
      turn('t1', 'user', '봐줘', [IMAGE, PDF]),
      turn('t2', 'assistant', '네'),
    ])
    expect(mine).toMatchObject({
      role: 'user',
      attachments: [
        { name: 'trail-map.jpg', kind: 'image', preview: '/api/attachments/a1?thumb=1' },
        { name: '지도.pdf', kind: 'pdf', preview: null, href: '/api/attachments/a3' },
      ],
    })
    expect(bot).not.toHaveProperty('attachments')
  })
})
