import { expect, test, type Page } from '@playwright/test'
import { latestSession, turnsOf } from './db.ts'

// 음성 대화 E2E(M3-16): 가짜 마이크(한국어 음성 wav, playwright.config.ts의 Chromium 플래그)와
// 가짜 음성 백엔드(인식 결과는 서버 설정의 고정 문장)·가짜 Claude CLI로 격리 서버에서 실제 브라우저로
// 시작 → 말하기 → 답변 재생 → 대화종료 → 일지까지 해 본다. OpenAI·Claude 사용량은 나가지 않는다.
// 같은 서버·DB를 모든 시험이 쓰므로 시험마다 새 대화를 시작하고 그 세션의 기록만 본다.

const FAKE_STT = '오늘 산책하면서 생각난 아이디어가 있어'

async function chooseVoice(page: Page) {
  await page.goto('/')
  const toggle = page.getByRole('group', { name: '대화 방식' })
  await expect(toggle.getByRole('button', { name: '음성으로' })).toBeEnabled({ timeout: 15_000 })
  await toggle.getByRole('button', { name: '음성으로' }).click()
}

async function startVoice(page: Page) {
  await chooseVoice(page)
  await page.getByRole('button', { name: '음성 대화 시작' }).click()
}

test.describe('음성 대화', () => {
  test('시작 → 말하기 → 답변 → 대화종료 → 일지까지 이어진다', async ({ page }) => {
    test.setTimeout(90_000)
    await startVoice(page)

    // 인사말 뒤 듣기 상태가 되고, 가짜 마이크의 음성이 인식되어 말풍선에 남는다
    const messages = page.getByRole('list', { name: '대화 내용' })
    await expect(messages).toBeVisible({ timeout: 20_000 })
    await expect(messages.getByRole('listitem').first()).toContainText('안녕하세요')
    await expect(messages).toContainText(FAKE_STT, { timeout: 30_000 })
    // 녹화된 첫 사용자 턴(save_note)의 답변이 온다
    await expect(messages).toContainText('노트에 저장해뒀어요', { timeout: 30_000 })

    const session = latestSession()
    const turns = turnsOf(session.id)
    expect(turns[0].greeting).toBe(1)
    expect(turns.find((t) => t.role === 'user')?.text).toBe(FAKE_STT)

    // 대화종료 → 확인 → 정리 중 → 일지
    await page.getByRole('button', { name: '대화종료' }).click()
    const dialog = page.getByRole('alertdialog', { name: '대화 종료 확인' })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: '끝내고 정리하기' }).click()
    await expect(page.getByRole('region', { name: '오늘의 정리' })).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => latestSession().status, { timeout: 30_000 }).toBe('ended')
  })
  test('마이크 권한이 없으면 대화를 마치고 이유를 알려 준다', async ({ page }) => {
    test.setTimeout(60_000)
    await page.addInitScript(`
      navigator.mediaDevices.getUserMedia = () =>
        Promise.reject(new DOMException('Permission denied', 'NotAllowedError'))
    `)
    await startVoice(page)
    await expect(page.getByText('마이크 권한이 없어요')).toBeVisible({ timeout: 30_000 })
  })

  test('음성 모듈을 불러오지 못하면 글 대화로 안내한다', async ({ page }) => {
    await chooseVoice(page) // 방식을 "음성으로"로 기억시킨다
    // 음성 모듈(vad-web 등)만 막는다. 기기 세션 같은 첫 화면 코드는 그대로 불러온다
    await page.route(/\/src\/platform\/(audioInput|audioOutput)\.ts/, (route) => route.abort())
    await page.reload()
    await expect(page.getByText('음성 기능을 불러오지 못했어요. 글로 대화해 주세요.')).toBeVisible()
    await expect(page.getByRole('button', { name: '글로 대화 시작' })).toBeVisible()
    await expect(
      page.getByRole('group', { name: '대화 방식' }).getByRole('button', { name: '음성으로' }),
    ).toBeDisabled()
  })

  test('일지 상세의 "음성으로 이어서"로 끝난 대화를 음성으로 다시 연다', async ({ page }) => {
    test.setTimeout(120_000)
    // 글 대화를 하나 끝내 일지를 만든다
    await page.goto('/')
    await page.getByRole('button', { name: '글로 대화 시작' }).click()
    const messages = page.getByRole('list', { name: '대화 내용' })
    await expect(messages).toBeVisible()
    await page.getByRole('textbox', { name: '메시지' }).fill('등산로 쓰레기통 지도 아이디어를 저장해줘')
    await page.getByRole('button', { name: '보내기' }).click()
    await expect(messages).toContainText('노트에 저장해뒀어요')
    const sessionId = latestSession().id
    await page.getByRole('button', { name: '대화종료' }).click()
    await page.getByRole('button', { name: '끝내고 정리하기' }).click()
    await expect(page.getByText('대화 끝남')).toBeVisible()

    await page.goto(`/journal/${sessionId}`)
    await page.getByRole('button', { name: '음성으로 이어서' }).click()
    // 같은 세션이 다시 열리고 마이크가 켜져 듣기 상태가 된다
    await expect(page.locator('.voice-dock')).toBeVisible({ timeout: 30_000 })
    await expect.poll(() => latestSession().id).toBe(sessionId)
    await expect.poll(() => latestSession().status, { timeout: 30_000 }).toBe('active')
    await expect(page.getByRole('button', { name: '대화종료' })).toBeVisible()
  })
})
