import { expect, test, type Page } from '@playwright/test'
import { latestSession, turnsOf } from './db.ts'
import { FAKE_SECRET, SERVER_NAME, calledTools } from './external-mcp.ts'

// 가짜 외부 MCP E2E(M5-14, FR-25): 서버 설정 파일(playwright.config.ts가 만든 임시 yaml)의 가짜 stdio
// 서버를 가짜 CLI가 mcp.json대로 실제로 띄워 호출한다. 허용 목록의 도구는 호출되고 허용 밖 도구는
// 서버가 호출되지 않으며, 비밀 값은 화면·응답·DB 어디에도 나오지 않는다. 실제 Claude CLI는 쓰지 않는다.
// (설정 파일이 틀리면 서버가 시작하지 않는 것은 서버 단위 시험 tests/test_external_mcp.py가 맡는다:
// webServer 기동 실패는 E2E에서 직접 보기 어렵다.)

async function startChat(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '글로 대화 시작' }).click()
  const messages = page.getByRole('list', { name: '대화 내용' })
  await expect(messages).toBeVisible()
  return messages
}

/** 메시지를 보내고 그 턴의 SSE 응답 본문 전체를 돌려준다 */
async function send(page: Page, text: string): Promise<string> {
  await page.getByRole('textbox', { name: '메시지' }).fill(text)
  const [response] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/turns') && r.request().method() === 'POST'),
    page.getByRole('button', { name: '보내기' }).click(),
  ])
  return response.text()
}

const tool = (name: string) => `__mcp__:mcp__${SERVER_NAME}__${name}`

test.describe('외부 MCP 도구', () => {
  test('허용 목록의 도구는 호출되고 화면에는 도구 이름과 결과만 보인다', async ({ page }) => {
    const before = calledTools().length
    const messages = await startChat(page)
    const body = await send(page, tool('allowed_ping'))
    await expect(messages).toContainText('allowed_ping 사용 완료')
    await expect(messages.locator('.tool-result')).toHaveText('allowed_ping ok')
    expect(calledTools().slice(before)).toEqual(['allowed_ping'])
    // 서버 이름은 도구 알림에 보이지 않는다(내가 보낸 지시어 말풍선에는 있다)
    await expect(messages.locator('.bubble-assistant').last()).not.toContainText(SERVER_NAME)
    // 서버가 보낸 tool 이벤트: 접두사를 포함한 이름, 인자는 null(가짜 CLI는 인자를 실어 보냈다)
    expect(body).toContain(`"name":"mcp__${SERVER_NAME}__allowed_ping"`)
    expect(body).not.toContain('사용자 발화 일부')
    expect(body).toMatch(/"phase":"call"[^\n]*"input":null/)
    // 결과는 DB에 저장되지 않는다
    const stored = turnsOf(latestSession().id).map((t) => t.text)
    expect(stored.join(' ')).not.toContain('allowed_ping ok')
  })

  test('허용 밖 도구는 호출되지 않는다', async ({ page }) => {
    const before = calledTools().length
    const messages = await startChat(page)
    // 설정이 명시적으로 막은 도구(--disallowedTools)와 허용 목록에 없는 도구 모두
    await send(page, tool('denied_ping'))
    await expect(messages).toContainText('denied_ping 사용하지 못했어요')
    await send(page, tool('never_listed'))
    await expect(messages).toContainText('never_listed 사용하지 못했어요')
    await expect(messages.locator('.tool-result')).toHaveCount(0)
    expect(calledTools().slice(before)).toEqual([]) // 서버가 한 번도 불리지 않았다
    // 허용 도구는 같은 대화에서 여전히 불린다
    await send(page, tool('allowed_ping'))
    await expect(messages).toContainText('allowed_ping 사용 완료')
    expect(calledTools().slice(before)).toEqual(['allowed_ping'])
  })

  test('비밀 값은 화면·응답·DB에 나오지 않는다', async ({ page }) => {
    const messages = await startChat(page)
    const bodies: string[] = []
    bodies.push(await send(page, tool('leak')))
    // 서버가 결과 속 비밀을 가리고 보낸다
    await expect(messages.locator('.tool-result')).toHaveText('key is ***')
    bodies.push(await send(page, tool('leak_error')))
    await expect(messages).toContainText('leak_error 사용하지 못했어요')
    for (const body of bodies) expect(body).not.toContain(FAKE_SECRET)
    expect(await page.content()).not.toContain(FAKE_SECRET)
    expect(await page.locator('body').innerText()).not.toContain(FAKE_SECRET)
    const stored = turnsOf(latestSession().id)
      .map((t) => t.text)
      .join(' ')
    expect(stored).not.toContain(FAKE_SECRET)
    // 설정 파일 경로·환경 변수 이름도 응답에 없다
    for (const body of bodies) expect(body).not.toMatch(/MCP_E2E_FAKE_API_KEY|mcp-servers/)
  })

  test('외부 서버는 빈 작업 폴더와 최소 환경에서 실행된다', async ({ page }) => {
    const messages = await startChat(page)
    await send(page, tool('probe'))
    const result = messages.locator('.tool-result')
    await expect(result).toBeVisible()
    const probe = JSON.parse((await result.innerText()).trim())
    expect(probe.cwd).toMatch(/\/mcp-e2e-fake$/) // CLI 작업 폴더 아래 전용 빈 폴더
    expect(probe.env).toContain('FAKE_API_KEY') // 설정 env의 변수
    expect(probe.env).toContain('PATH')
    for (const name of [
      'CLAUDE_CODE_OAUTH_TOKEN',
      'OPENAI_API_KEY',
      'DATABASE_URL',
      'MCP_E2E_FAKE_API_KEY',
    ]) {
      expect(probe.env).not.toContain(name) // 서버 환경은 상속되지 않는다
    }
  })
})
