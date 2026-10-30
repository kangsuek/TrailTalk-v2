import { expect, test } from '@playwright/test'
import { connectMcp, type McpClient } from './mcp.ts'

// Claude 앱 연계 E2E(MA-11): 외부 MCP 서버(8401)에 OAuth로 연결해 도구를 부르고, 기존 웹 화면(격리
// 서버 8100 뒤의 Vite)에 앱에서 저장한 일지·노트가 보이는지, 웹에서 고친 노트가 get_journal에 반영되는지,
// 앱에서 지운 노트가 웹에서 사라지는지 브라우저로 확인한다. 이 파일은 마지막에 돌도록 z-로 시작한다
// (앱 세션이 "가장 최근 세션"을 읽는 다른 시험의 전제를 바꾸지 않게).

const TITLE = 'E2E 앱 일지'

async function ok(mcp: McpClient, name: string, args: Record<string, unknown>) {
  const result = await mcp.call(name, args)
  expect(result.isError, result.text).toBe(false)
  return result.text
}

test.describe('Claude 앱 연계', () => {
  test('앱에서 저장한 일지가 웹에 보이고, 웹과 앱의 수정·삭제가 서로 반영된다', async ({ page }) => {
    const mcp = await connectMcp()
    const saved = await ok(mcp, 'save_journal', {
      title: TITLE,
      summary: '앱에서 정리한 결론\n앱에서 알게 된 것',
      ideas: ['앱 아이디어 하나', '앱 아이디어 둘'],
      todos: ['앱 할 일'],
      tags: ['앱연계'],
      transcript: '나: 오늘 산책 어땠어\nClaude: 좋았어요',
    })
    const journalId = saved.match(/id ([0-9a-f]{8})/)![1]

    // 웹 일지 목록에 앱 일지가 보이고 상세에서 요약·노트·전문이 보인다
    await page.goto('/')
    await page.getByRole('navigation').getByRole('button', { name: '일지' }).click()
    const card = page.getByRole('button', { name: new RegExp(TITLE) })
    await expect(card).toBeVisible()
    await card.click()
    await expect(page.getByRole('region', { name: '결론' })).toContainText('앱에서 정리한 결론')
    await expect(page.getByRole('region', { name: '알게 된 것' })).toContainText('앱에서 알게 된 것')
    await expect(page.getByRole('region', { name: '아이디어' })).toContainText('앱 아이디어 하나')
    await expect(page.getByRole('region', { name: '할 일' })).toContainText('앱 할 일')
    await expect(page.getByRole('list', { name: '태그' })).toContainText('앱연계')

    // 웹에서 아이디어에 별표를 누르면 앱의 get_journal에 ★로 나온다
    const idea = page.getByRole('region', { name: '아이디어' }).getByRole('listitem').first()
    await idea.getByRole('button', { name: '별표' }).click()
    await expect
      .poll(async () => (await ok(mcp, 'get_journal', { id: journalId })), { timeout: 10_000 })
      .toMatch(/앱 아이디어 하나 ★/)

    // 앱에서 아이디어를 2단계 확인으로 지우면 웹에서도 사라진다
    const list = await ok(mcp, 'list_notes', { kind: 'idea' })
    const noteId = list.split('\n').find((line) => line.includes('앱 아이디어 둘'))!.split(' ')[0]
    const preview = await ok(mcp, 'delete_note', { id: noteId })
    const token = preview.split('확인 값: ')[1].replace(/\)$/, '')
    await ok(mcp, 'delete_note', { id: noteId, confirm_token: token })
    await page.reload()
    await expect(page.getByRole('region', { name: '아이디어' })).not.toContainText('앱 아이디어 둘')
    await expect(page.getByRole('region', { name: '아이디어' })).toContainText('앱 아이디어 하나')

    // 앱 메모(save_note)도 목록에 그날의 앱 메모 세션으로 보인다
    await ok(mcp, 'save_note', { kind: 'idea', content: 'E2E 앱 메모 노트' })
    await page.goto('/')
    await page.getByRole('navigation').getByRole('button', { name: '일지' }).click()
    await expect(page.getByRole('button', { name: /앱 메모/ })).toBeVisible()
  })

  test('외부 MCP 포트는 웹 API와 웹 화면을 열지 않는다', async ({ request }) => {
    for (const path of ['/api/health', '/api/journal', '/internal/mcp/', '/']) {
      const response = await request.get(`http://127.0.0.1:8401${path}`)
      expect(response.status(), path).toBe(404)
    }
    const unauth = await request.post('http://127.0.0.1:8401/mcp', { data: {} })
    expect(unauth.status()).toBe(401)
  })
})
