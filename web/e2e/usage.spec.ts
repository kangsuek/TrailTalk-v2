import { expect, test, type Page } from '@playwright/test'

// 헤더 오른쪽의 남은 토큰 막대(M5-03). 한도 값은 /api/usage를 가짜로 바꿔 정하고, 서버 연동은
// 가짜 Claude CLI가 녹화한 한도(5시간 사용률 0.4)로 확인한다.

const body = (used: number | null, hours = 3.5) => ({
  status: 'allowed',
  five_hour:
    used === null
      ? null
      : {
          utilization: used,
          resets_at: new Date(Date.now() + hours * 3_600_000).toISOString(),
        },
  seven_day: null,
  updated_at: used === null ? null : new Date().toISOString(),
})

async function fakeUsage(page: Page, used: number | null) {
  await page.route('**/api/usage', (route) => route.fulfill({ json: body(used) }))
}

const meter = (page: Page) => page.getByRole('meter', { name: 'Claude 남은 토큰' })

test.describe('남은 토큰 막대', () => {
  test('남은 %와 초기화 시각을 헤더 오른쪽에 보인다', async ({ page }) => {
    await fakeUsage(page, 0.38)
    await page.goto('/')
    await expect(meter(page)).toContainText('남은 토큰 62%')
    await expect(meter(page)).toContainText('시간 뒤 초기화')
    await expect(meter(page)).toHaveAttribute('aria-valuenow', '62')
  })

  test('값이 없으면(첫 답변 전) 막대를 비우고 안내한다', async ({ page }) => {
    await fakeUsage(page, null)
    await page.goto('/')
    await expect(meter(page)).toContainText('대화하면 표시')
    await expect(meter(page)).not.toHaveAttribute('aria-valuenow')
  })

  test('20% 이하면 경고, 0%면 소진 색으로 바뀐다', async ({ page }) => {
    await fakeUsage(page, 0.85)
    await page.goto('/')
    await expect(meter(page)).toHaveAttribute('data-level', 'low')
    await page.unroute('**/api/usage')
    await fakeUsage(page, 1)
    await page.reload()
    await expect(meter(page)).toHaveAttribute('data-level', 'out')
  })

  test('서버에 닿지 않으면 확인 불가로 보인다', async ({ page }) => {
    await page.clock.install() // 30초 갱신 타이머를 앞당기려고 시계를 쥔다
    await fakeUsage(page, 0.38)
    await page.goto('/')
    await expect(meter(page)).toContainText('62%')
    await page.route('**/api/health', (route) => route.abort())
    await page.route('**/api/usage', (route) => route.abort())
    await page.clock.fastForward(31_000)
    await expect(meter(page)).toContainText('확인 불가')
  })

  for (const scheme of ['light', 'dark'] as const) {
    test(`시각 기준: 헤더의 막대(${scheme})`, async ({ browser }) => {
      const context = await browser.newContext({
        colorScheme: scheme,
        viewport: { width: 360, height: 800 },
      })
      const page = await context.newPage()
      await page.route('**/api/usage', (route) =>
        route.fulfill({
          json: {
            ...body(0.38),
            five_hour: { utilization: 0.38, resets_at: '2099-01-01T00:00:00Z' },
          },
        }),
      )
      await page.clock.setFixedTime(new Date('2098-12-31T20:30:00Z')) // 초기화 3시간 30분 전으로 고정
      await page.goto('/')
      await expect(meter(page)).toContainText('62%')
      await expect(page.locator('.app-header')).toHaveScreenshot(`usage-header-${scheme}.png`)
      await context.close()
    })
  }

  test('실제 서버: 답변을 받은 뒤 CLI가 알려 준 한도가 보인다', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('button', { name: '글로 대화 시작' }).click()
    await expect(page.getByRole('list', { name: '대화 내용' })).toBeVisible()
    await page.getByRole('textbox', { name: '메시지' }).fill('__say__:안녕하세요')
    await page.getByRole('button', { name: '보내기' }).click()
    await expect(page.locator('.bubble-assistant').last()).toContainText('안녕하세요')
    await page.reload()
    await expect(meter(page)).toContainText(/남은 토큰 \d+%/)
  })
})
