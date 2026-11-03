import { existsSync } from 'node:fs'
import { expect, test, type Page, type TestInfo } from '@playwright/test'

// 시각 회귀(M3-16): 음성 대화의 시작·듣기·처리 중·말하기 화면을 라이트·다크로 기준 이미지와 비교한다.
// 순간적인 상태는 이렇게 붙잡는다.
//  - 듣기: 조용한 가짜 마이크(무음 스트림)로 인사말이 끝난 뒤 머문다
//  - 말하기: 인사말을 길이 20초의 무음으로 바꿔 재생 중에 머문다
//  - 처리 중: 가짜 마이크의 음성을 보내고, 음성 턴 요청을 붙잡아 두고 있는 동안 찍는다
// 시각 시험은 한 DB를 공유하는 전체 실행(workers 1)의 순서에서 돈다. 기준 이미지는 `npm run e2e:update`로
// 전체를 돌려 만든다. 기준 이미지가 없는 OS에서는 건너뛴다(visual.spec.ts와 같은 규칙). 만들거나 갱신하려면
// `npm run e2e:update`를 실행하고 눈으로 확인한 뒤 커밋한다.

const SCHEMES = ['light', 'dark'] as const

async function silentMic(page: Page) {
  // e2e 프로젝트에는 DOM 타입이 없어 브라우저에서 돌 코드는 문자열로 준다
  await page.addInitScript(`
    navigator.mediaDevices.getUserMedia = async () =>
      new AudioContext().createMediaStreamDestination().stream
  `)
}

async function openVoiceStart(page: Page) {
  // 앞선 시험이 남긴 아이디어가 "지난 아이디어" 카드로 보이지 않게 빈 목록으로 고정한다
  await page.route('**/api/notes/open-ideas*', (route) => route.fulfill({ json: [] }))
  // 앞선 시험이 서버에 남긴 한도 값이 헤더 막대에 보이지 않게 첫 답변 전 상태로 고정한다
  await page.route('**/api/usage', (route) =>
    route.fulfill({ json: { status: null, five_hour: null, seven_day: null, updated_at: null } }),
  )
  await page.goto('/')
  const toggle = page.getByRole('group', { name: '대화 방식' })
  await expect(toggle.getByRole('button', { name: '음성으로' })).toBeEnabled({ timeout: 15_000 })
  await toggle.getByRole('button', { name: '음성으로' }).click()
  await expect(page.getByRole('status')).toHaveText(/연결됨/)
}

for (const scheme of SCHEMES) {
  test.describe(`음성 화면(${scheme})`, () => {
    test.use({ colorScheme: scheme })

    // 기준이 없는 OS에서는 건너뛴다(`npm run e2e:update`로 만들 때는 건너뛰지 않는다)
    const shot = async (page: Page, name: string, testInfo: TestInfo) => {
      const baseline = testInfo.snapshotPath(`${name}-${scheme}.png`)
      test.skip(
        !existsSync(baseline) && testInfo.config.updateSnapshots !== 'all',
        '이 OS의 기준 이미지가 없습니다',
      )
      await expect(page).toHaveScreenshot(`${name}-${scheme}.png`, { maxDiffPixels: 150 })
    }

    test('시작', async ({ page }, testInfo) => {
      await openVoiceStart(page)
      await expect(page.getByRole('button', { name: '음성 대화 시작' })).toBeVisible()
      await shot(page, 'voice-start', testInfo)
    })

    test('듣는 중', async ({ page }, testInfo) => {
      await silentMic(page)
      await openVoiceStart(page)
      await page.getByRole('button', { name: '음성 대화 시작' }).click()
      await expect(page.locator('.voice-dock')).toHaveAttribute('data-state', 'listening', {
        timeout: 30_000,
      })
      await expect(page.getByText('편하게 말씀하세요')).toBeVisible()
      await shot(page, 'voice-listening', testInfo)
    })

    test('말하는 중', async ({ page }, testInfo) => {
      await silentMic(page)
      // 인사말 소리를 20초짜리 무음으로 바꿔 재생 중 상태에 머물게 한다
      await page.addInitScript(`
        AudioContext.prototype.decodeAudioData = function () {
          return Promise.resolve(this.createBuffer(1, this.sampleRate * 20, this.sampleRate))
        }
      `)
      await openVoiceStart(page)
      await page.getByRole('button', { name: '음성 대화 시작' }).click()
      await expect(page.locator('.voice-dock')).toHaveAttribute('data-state', 'speaking', {
        timeout: 30_000,
      })
      await shot(page, 'voice-speaking', testInfo)
    })

    test('처리 중', async ({ page }, testInfo) => {
      // 음성 턴 요청을 붙잡아 두면 인식·답변을 기다리는 처리 중 상태에 머문다
      let release: () => void = () => {}
      const hold = new Promise<void>((resolve) => (release = resolve))
      await page.route('**/turns/audio', async (route) => {
        await hold
        await route.abort()
      })
      await openVoiceStart(page)
      const requested = page.waitForRequest('**/turns/audio', { timeout: 40_000 })
      await page.getByRole('button', { name: '음성 대화 시작' }).click()
      await requested // 가짜 마이크의 말이 잡혀 음성 턴 요청이 나간 뒤에 상태를 본다
      await expect(page.locator('.voice-dock')).toHaveAttribute('data-state', 'processing', {
        timeout: 40_000,
      })
      await shot(page, 'voice-processing', testInfo)
      release()
    })
  })
}
