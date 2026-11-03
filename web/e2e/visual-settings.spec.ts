import { existsSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

// 시각 회귀(M5-05): 설정 화면을 시안 설정 01·02·03과 같은 세 구간(내 정보 / 대화 모델 / 화면 모드·앱)으로
// 라이트·다크 기준 이미지와 비교한다. 프로필은 가짜 응답으로 고정한다(앞선 시험이 DB에 남긴 값에 흔들리지 않게).
// 기준이 없는 OS에서는 건너뛴다(visual.spec.ts와 같은 규칙). 만들거나 갱신하려면 `npm run e2e:update`를
// 실행하고 눈으로 확인한 뒤 커밋한다.

const PROFILE = {
  nickname: '다니엘',
  interests: ['전시', '테크', '등산', '맛집'],
  persona_id: 'jenny',
  voice: null,
  speaking_rate: null,
  ack_enabled: true,
  keep_audio: false,
  chat_model: null,
  default_chat_model: 'sonnet',
}

// .set-body를 얼마나 내려서 찍을지: 맨 위 / 대화 모델이 보이는 곳 / 맨 아래
const SECTIONS: [string, string][] = [
  ['info', '0'],
  [
    'model',
    `(() => { const b = document.querySelector('.set-body'); const s = document.querySelector('[aria-label="대화 모델"]'); return s.getBoundingClientRect().top - b.getBoundingClientRect().top + b.scrollTop - 16 })()`,
  ],
  ['app', 'document.querySelector(".set-body").scrollHeight'],
]

async function open(page: Page) {
  await page.route('**/api/profile', (route) =>
    route.request().method() === 'GET'
      ? route.fulfill({ json: { ...PROFILE, client: {} } })
      : route.fallback(),
  )
  await page.goto('/settings')
  await expect(page.getByLabel('호칭')).toHaveValue('다니엘')
  await expect(page.locator('.set-conn')).toHaveText('연결됨')
  await page.evaluate('document.fonts.ready')
}

for (const scheme of ['light', 'dark'] as const) {
  for (const [name, top] of SECTIONS) {
    test(`설정 ${name}(${scheme})`, async ({ browser }, testInfo) => {
      const baseline = testInfo.snapshotPath(`settings-${name}-${scheme}.png`)
      test.skip(
        !existsSync(baseline) && testInfo.config.updateSnapshots !== 'all',
        '이 OS의 기준 이미지가 없습니다',
      )
      const context = await browser.newContext({
        colorScheme: scheme,
        timezoneId: 'Asia/Seoul',
        locale: 'ko-KR',
      })
      const page = await context.newPage()
      await open(page)
      await page.evaluate(`document.querySelector('.set-body').scrollTop = ${top}`)
      await expect(page).toHaveScreenshot(`settings-${name}-${scheme}.png`, { maxDiffPixels: 150 })
      await context.close()
    })
  }
}
