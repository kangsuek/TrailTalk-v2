import { expect, test } from '@playwright/test'
import { latestSession, turnsOf } from './db.ts'

// 출처 인용 E2E(M5-10): 가짜 CLI가 검색 도구를 쓴 턴(`__play__:web_search` 녹화)을 내면 답변 말풍선에
// 출처 호스트가 보이고, 서버가 turn.sources에 저장하며, 대화를 끝내면 일지 정리(추출 녹화는 결론에
// 출처 [1]을 단다)가 일지 상세에 인용 구역과 번호를 채운다. 검색하지 않은 대화는 인용이 없다.

test.describe('출처 인용', () => {
  test('검색한 대화: 말풍선 출처 → 저장 → 일지 상세 인용', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '글로 대화 시작' }).click()
    const messages = page.getByRole('list', { name: '대화 내용' })
    await expect(messages).toBeVisible()
    await page.getByRole('textbox', { name: '메시지' }).fill('__play__:web_search')
    await page.getByRole('button', { name: '보내기' }).click()
    await expect(messages).toContainText('최신 uv 버전을 찾았어요')

    // 말풍선 아래: 서버가 준 호스트(www. 뗌, 최대 3개)가 링크 아닌 글자로 보인다
    const chips = messages.getByRole('list', { name: '출처' })
    await expect(chips.getByRole('listitem')).toHaveText([
      'github.com',
      'docs.astral.sh',
      'blog.example.com',
    ])
    await expect(chips.getByRole('link')).toHaveCount(0)

    // 서버는 이 턴의 출처(링크 4개)를 저장했다
    const session = latestSession()
    const reply = turnsOf(session.id).at(-1)!
    expect(JSON.parse(reply.sources!).map((s: { host: string }) => s.host)).toEqual([
      'github.com',
      'docs.astral.sh',
      'blog.example.com',
      'fourth.example.org',
    ])

    // 끝내면 정리가 끝난 일지 상세에 인용 구역과 문장 끝 번호가 생긴다
    await page.getByRole('button', { name: '대화종료' }).click()
    await page.getByRole('button', { name: '끝내고 정리하기' }).click()
    await expect(page.getByText('대화 끝남')).toBeVisible()
    await page.goto(`/journal/${session.id}`)
    await expect(page.getByRole('region', { name: '결론' })).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('region', { name: '결론' })).toContainText('[1]')
    const cites = page.getByRole('region', { name: '인용' })
    await expect(cites).toContainText('[1] uv 릴리스')
    await expect(cites.getByRole('link', { name: 'uv 릴리스' })).toHaveAttribute(
      'href',
      'https://www.github.com/astral-sh/uv/releases',
    )
    // 전문의 답변 말풍선에도 출처가 남는다(저장된 호스트 4개)
    await page.getByRole('button', { name: /전문/ }).click()
    await expect(
      page
        .getByRole('list', { name: '전문' })
        .getByRole('list', { name: '출처' })
        .getByRole('listitem'),
    ).toHaveText(['github.com', 'docs.astral.sh', 'blog.example.com', 'fourth.example.org'])
  })

  test('검색하지 않은 대화는 출처 칩도 인용도 없다', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '글로 대화 시작' }).click()
    const messages = page.getByRole('list', { name: '대화 내용' })
    await page.getByRole('textbox', { name: '메시지' }).fill('__say__:그냥 이야기해요.')
    await page.getByRole('button', { name: '보내기' }).click()
    await expect(messages).toContainText('그냥 이야기해요.')
    await expect(page.getByRole('list', { name: '출처' })).toHaveCount(0)
    const session = latestSession()
    expect(JSON.parse(turnsOf(session.id).at(-1)!.sources ?? 'null')).toBeNull() // 출처 없음
    await page.getByRole('button', { name: '대화종료' }).click()
    await page.getByRole('button', { name: '끝내고 정리하기' }).click()
    await expect(page.getByText('대화 끝남')).toBeVisible()
    await page.goto(`/journal/${session.id}`)
    await expect(page.getByRole('region', { name: '결론' })).toBeVisible({ timeout: 20_000 })
    await expect(page.getByRole('region', { name: '인용' })).toHaveCount(0) // 모델이 단 [1]은 버려진다
    await expect(page.getByRole('region', { name: '결론' })).not.toContainText('[1]')
  })
})
