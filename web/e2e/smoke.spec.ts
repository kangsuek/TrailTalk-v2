import { existsSync, statSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test } from '@playwright/test'

test.describe('스모크', () => {
  test('앱이 뜨고 서버 연결됨이 보인다', async ({ page }) => {
    await page.goto('/')
    await expect(page.getByRole('heading', { name: 'TrailTalk' })).toBeVisible()
    await expect(page.getByRole('status')).toHaveText(/연결됨/)
  })

  test('하단 탭 세 개를 눌러 바꾼다', async ({ page }) => {
    await page.goto('/')
    const nav = page.getByRole('navigation', { name: '메인 메뉴' })
    await expect(nav.getByRole('button')).toHaveText(['대화', '일지', '설정'])
    for (const name of ['일지', '설정', '대화']) {
      await nav.getByRole('button', { name }).click()
      await expect(nav.getByRole('button', { name })).toHaveAttribute('aria-current', 'page')
      await expect(page.getByText(`${name} 화면은 준비 중입니다.`)).toBeVisible()
    }
  })

  test('서버에 닿지 않으면 연결 안 됨을 보인다', async ({ page }) => {
    await page.route('**/api/health', (route) => route.abort())
    await page.goto('/')
    await expect(page.getByRole('status')).toHaveText(/연결 안 됨/)
  })

  test('확인 중 글자색은 대비를 맞춘 호박색이다(라이트)', async ({ browser }) => {
    const context = await browser.newContext({ colorScheme: 'light' })
    const page = await context.newPage()
    await page.route('**/api/health', () => {}) // 응답을 주지 않아 확인 중으로 둔다
    await page.goto('/')
    const status = page.getByRole('status')
    await expect(status).toHaveText(/확인 중/)
    await expect(status).toHaveCSS('color', 'rgb(156, 92, 0)')
    await context.close()
  })

  test('E2E 서버는 임시 폴더만 쓰고 실제 server/data를 건드리지 않는다', async ({ request }) => {
    const realDb = resolve(import.meta.dirname, '../../server/data/trailtalk.db')
    const before = existsSync(realDb) ? statSync(realDb).mtimeMs : null
    const response = await request.get('http://127.0.0.1:8100/api/health')
    expect(response.status()).toBe(200)
    // 격리 서버는 web/.e2e/data 아래에 DB를 만든다
    expect(existsSync(resolve(import.meta.dirname, '../.e2e/data/trailtalk.db'))).toBe(true)
    // 실제 DB는 만들어지지도 바뀌지도 않는다(E2E 시작 전에 없었다면 지금도 없어야 한다)
    const after = existsSync(realDb) ? statSync(realDb).mtimeMs : null
    expect(after).toBe(before)
  })
})
