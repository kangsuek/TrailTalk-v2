import { expect, test, type Page } from '@playwright/test'

// 설정 화면(M5-05): 격리 서버의 실제 프로필 API로 저장·유지를 확인하고, 거절(422)은 PUT을 가짜로 바꿔 확인한다.
// 같은 서버·DB를 모든 시험이 쓰므로 시험 끝에 바꾼 값을 처음 상태로 돌린다.

const openSettings = async (page: Page) => {
  await page.goto('/settings')
  await expect(page.getByRole('heading', { name: '설정', level: 1 })).toBeVisible()
  await expect(page.getByLabel('호칭')).toBeVisible()
}

// 앞선 시험이 DB에 남긴 값에 기대지 않고, 끝난 뒤에도 남기지 않도록 프로필을 처음 상태로 맞춘다
const resetProfile = (page: Page) =>
  page.request.put('/api/profile', { data: { nickname: null, interests: [], chat_model: null } })

test.describe('설정', () => {
  test.beforeEach(async ({ page }) => {
    await resetProfile(page)
  })
  test.afterEach(async ({ page }) => {
    await resetProfile(page)
  })

  test('호칭·관심사·대화 모델을 바꾸면 바로 저장되고 새로고침 뒤에도 남는다', async ({ page }) => {
    await openSettings(page)

    const nickname = page.getByLabel('호칭')
    await nickname.fill('다니엘')
    await nickname.press('Enter')
    await expect(page.getByText('저장됨')).toBeVisible()

    await page.getByLabel('관심사 추가').fill('등산')
    await page.getByLabel('관심사 추가').press('Enter')
    await expect(page.getByRole('list', { name: '관심사 목록' })).toContainText('등산')

    await page.getByRole('radio', { name: /^opus/ }).click()
    await expect(page.getByRole('radio', { name: /^opus/ })).toHaveAttribute('aria-checked', 'true')

    await page.reload()
    await expect(page.getByLabel('호칭')).toHaveValue('다니엘')
    await expect(page.getByRole('list', { name: '관심사 목록' })).toContainText('등산')
    await expect(page.getByRole('radio', { name: /^opus/ })).toHaveAttribute('aria-checked', 'true')
  })

  test('서버가 거절(422)하면 그 필드 옆에 이유를 보이고 값을 되돌린다', async ({ page }) => {
    await openSettings(page)
    const before = await page.getByLabel('호칭').inputValue()
    await page.route('**/api/profile', (route) => {
      if (route.request().method() !== 'PUT') return route.fallback()
      return route.fulfill({
        status: 422,
        json: { error: { code: 'validation_error', message: '호칭이 올바르지 않아요.' } },
      })
    })
    await page.getByLabel('호칭').fill('민지')
    await page.getByLabel('호칭').press('Enter')
    await expect(page.getByRole('alert')).toHaveText('호칭이 올바르지 않아요.')
    await expect(page.getByText('저장 안 됨')).toBeVisible()
    await expect(page.getByLabel('호칭')).toHaveValue(before)
  })

  test('화면 모드를 고르면 바로 적용되고 새로고침 뒤에도 남는다(이 기기에만)', async ({ page }) => {
    await openSettings(page)
    await page.getByRole('radio', { name: /^다크/ }).click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect(page.getByRole('radio', { name: /^다크/ })).toHaveAttribute('aria-checked', 'true')
    await page.getByRole('radio', { name: /^시스템 설정 따르기/ }).click()
    await expect
      .poll(() => page.evaluate("document.documentElement.hasAttribute('data-theme')"))
      .toBe(false)
  })

  test('보류한 항목(이메일·보이스·말 속도·맞장구·음성 원본)은 없다', async ({ page }) => {
    await openSettings(page)
    await expect(page.getByText(/이메일|보이스|목소리|말 속도|맞장구|음성 원본/)).toHaveCount(0)
  })

  test('서버 연결 상태를 앱 정보에 보인다', async ({ page }) => {
    await openSettings(page)
    await expect(page.locator('.set-conn')).toHaveText('연결됨')
  })
})
