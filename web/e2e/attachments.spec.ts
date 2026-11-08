import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { attachmentsOf, latestSession, turnsOf } from './db.ts'

// 파일 첨부 E2E(M5-08): 격리 서버(가짜 CLI)에 이미지·텍스트·PDF를 글과 함께 보내고, 말풍선과 일지 상세
// 전문의 썸네일·칩, 서버 기록, 오류 복구를 브라우저에서 실제로 해 본다. 가짜 CLI는 첨부 블록을 받아도
// 첫 사용자 턴에는 녹화 턴(노트 저장 도구 + "노트에 저장해뒀어요")으로 답한다.

const FIXTURES = resolve(import.meta.dirname, 'fixtures')
const PNG = resolve(FIXTURES, 'trail-map.png')
const TXT = resolve(FIXTURES, 'course-memo.txt')
const PDF = resolve(FIXTURES, 'course-memo.pdf')

async function startConversation(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '글로 대화 시작' }).click()
  await expect(page.getByRole('list', { name: '대화 내용' })).toBeVisible()
}

test.describe('파일 첨부', () => {
  test('이미지·텍스트·PDF를 글과 함께 보내면 말풍선과 일지 전문에 썸네일·칩이 보인다', async ({
    page,
  }) => {
    await startConversation(page)
    await expect(page.getByText('첨부는 글과 함께 보내요 · 최대 3개')).toBeVisible()
    await page.locator('input[type=file]').setInputFiles([PNG, TXT, PDF])
    const picked = page.getByRole('list', { name: '보낼 첨부' })
    await expect(picked).toContainText('trail-map.png')
    await expect(picked).toContainText('course-memo.txt')
    await expect(picked).toContainText('course-memo.pdf')

    // 글이 비면 보내지 못하고 힌트를 보인다
    await expect(page.getByText('파일과 함께 보낼 글을 적어 주세요.')).toBeVisible()
    await expect(page.getByRole('button', { name: '보내기' })).toBeDisabled()

    // 하나 빼 보고 다시 담는다
    await page.getByRole('button', { name: 'course-memo.txt 첨부 빼기' }).click()
    await expect(picked).not.toContainText('course-memo.txt')
    await page.locator('input[type=file]').setInputFiles([TXT])
    await expect(picked).toContainText('course-memo.txt')

    await page.getByRole('textbox', { name: '메시지' }).fill('이 자료로 전망대 코스를 정리해줘')
    await page.getByRole('button', { name: '보내기' }).click()

    const messages = page.getByRole('list', { name: '대화 내용' })
    await expect(messages).toContainText('노트에 저장해뒀어요')
    await expect(page.getByRole('list', { name: '보낼 첨부' })).toHaveCount(0)
    const mine = messages.locator('.bubble-user').last()
    await expect(mine.getByAltText('trail-map.png')).toBeVisible()
    await expect(mine).toContainText('course-memo.txt')
    await expect(mine).toContainText('course-memo.pdf')
    await expect(mine).toContainText('이 자료로 전망대 코스를 정리해줘')

    // 서버 기록: 사용자 턴에 글만, 첨부 3개(이미지는 썸네일 포함)
    const session = latestSession()
    const turns = turnsOf(session.id)
    expect(turns[1].text).toBe('이 자료로 전망대 코스를 정리해줘')
    // 서버는 알파가 없는 이미지를 JPEG로 다시 인코딩한다(이름은 그대로)
    const rows = attachmentsOf(session.id).sort((a, b) => a.name.localeCompare(b.name))
    expect(rows.map((r) => [r.name, r.mime, r.role])).toEqual([
      ['course-memo.pdf', 'application/pdf', 'user'],
      ['course-memo.txt', 'text/plain', 'user'],
      ['trail-map.png', 'image/jpeg', 'user'],
    ])
    expect(rows.find((r) => r.name === 'trail-map.png')?.thumb_path).toBeTruthy()

    // 대화를 끝내고 일지 상세 전문을 열면 서버 썸네일과 파일 칩이 보인다
    await page.getByRole('button', { name: '대화종료' }).click()
    await page.getByRole('button', { name: '끝내고 정리하기' }).click()
    await expect(page.getByText('대화 끝남')).toBeVisible()
    await page.goto(`/journal/${session.id}`)
    await expect(page.getByRole('region', { name: '결론' })).toBeVisible({ timeout: 20_000 })
    await page.getByRole('button', { name: /전문/ }).click()
    const transcript = page.getByRole('list', { name: '전문' })
    const thumb = transcript.getByAltText('trail-map.png')
    await expect(thumb).toBeVisible()
    await expect(thumb).toHaveAttribute('src', /\/api\/attachments\/[\w-]+\?thumb=1$/)
    expect(
      await thumb.evaluate((img) => (img as unknown as { naturalWidth: number }).naturalWidth),
    ).toBeGreaterThan(0)
    const chip = transcript.getByRole('link', { name: /course-memo\.pdf/ })
    await expect(chip).toHaveAttribute('href', /\/api\/attachments\/[\w-]+$/)
    await expect(transcript.getByRole('link', { name: /course-memo\.txt/ })).toBeVisible()

    // 원본 주소는 PDF를 내려받게 준다
    const response = await page.request.get((await chip.getAttribute('href'))!)
    expect(response.headers()['content-type']).toBe('application/pdf')
    expect(response.headers()['x-content-type-options']).toBe('nosniff')
  })

  for (const scheme of ['light', 'dark'] as const) {
    test(`새로고침 뒤 내 말풍선의 파일 칩 글자가 읽힌다(${scheme} 모드)`, async ({ page }) => {
      // 서버에 저장된 첨부는 링크(<a>) 칩인데, 말풍선의 링크 색 상속(.bubble a)이 칩 글자색을 덮어
      // 흰 바탕에 흰 글씨가 되던 결함(2026-11-08 실제 브라우저에서 발견)
      await page.emulateMedia({ colorScheme: scheme })
      await startConversation(page)
      await page.locator('input[type=file]').setInputFiles([TXT, PDF])
      await page.getByRole('textbox', { name: '메시지' }).fill('이 메모를 읽어줘')
      await page.getByRole('button', { name: '보내기' }).click()
      await expect(page.getByRole('list', { name: '대화 내용' })).toContainText(
        '노트에 저장해뒀어요',
      )

      await page.reload()
      const chip = page
        .locator('.bubble-user')
        .last()
        .getByRole('link', { name: /course-memo\.pdf/ })
      await expect(chip).toBeVisible()
      // 칩 바탕은 밝은 반투명이라 글자는 어두운 색(#16241d)이어야 한다
      await expect(chip).toHaveCSS('color', 'rgb(22, 36, 29)')
    })
  }

  test('서버가 첨부를 거절하면 쓴 글과 첨부 목록이 입력창에 돌아온다', async ({ page }) => {
    await startConversation(page)
    // 이미지 확장자지만 내용이 이미지가 아니라서 서버가 거절한다(400 attachment_invalid)
    await page.locator('input[type=file]').setInputFiles({
      name: 'fake.png',
      mimeType: 'image/png',
      buffer: Buffer.from('이건 그림이 아니에요'),
    })
    await page.getByRole('textbox', { name: '메시지' }).fill('이 그림 좀 봐줘')
    await page.getByRole('button', { name: '보내기' }).click()

    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('textbox', { name: '메시지' })).toHaveValue('이 그림 좀 봐줘')
    await expect(page.getByRole('list', { name: '보낼 첨부' })).toContainText('fake.png')
    // 서버가 받지 못했으니 내 말풍선도 기록도 남지 않는다
    await expect(page.locator('.bubble-user')).toHaveCount(0)
    expect(turnsOf(latestSession().id).map((t) => t.role)).toEqual(['assistant'])

    // 첨부를 빼고 글만 다시 보내면 정상으로 간다
    await page.getByRole('button', { name: 'fake.png 첨부 빼기' }).click()
    await page.getByRole('button', { name: '보내기' }).click()
    await expect(page.getByRole('list', { name: '대화 내용' })).toContainText('노트에 저장해뒀어요')
  })

  test('형식이 안 맞는 파일은 담지 않고 안내한다', async ({ page }) => {
    await startConversation(page)
    await page.locator('input[type=file]').setInputFiles({
      name: 'run.exe',
      mimeType: 'application/octet-stream',
      buffer: Buffer.from('MZ'),
    })
    await expect(page.getByText(/run\.exe: 지원하지 않는 형식/)).toBeVisible()
    await expect(page.getByRole('list', { name: '보낼 첨부' })).toHaveCount(0)
  })
})
