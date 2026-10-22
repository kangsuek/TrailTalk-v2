import { existsSync } from 'node:fs'
import { expect, test } from '@playwright/test'

// 시각 회귀: 360×800 화면을 기준 이미지와 비교한다.
// 기준 이미지는 이 OS(플랫폼별 폴더)에서 만든 것만 쓴다. 기준이 없는 OS(예: CI의 Linux)에서는
// 건너뛴다. 만들거나 갱신하려면 `npm run e2e:update`를 실행하고 눈으로 확인한 뒤 커밋한다.
// 핵심 화면(대화·일지·설정)의 기준 이미지는 화면이 생기는 M2~M3에서 더한다.
for (const scheme of ['light', 'dark'] as const) {
  test(`빈 앱 화면(${scheme})`, async ({ browser }, testInfo) => {
    const baseline = testInfo.snapshotPath(`app-${scheme}.png`)
    test.skip(!existsSync(baseline) && !testInfo.config.updateSnapshots.match(/all|changed|missing/), '이 OS의 기준 이미지가 없습니다')
    const context = await browser.newContext({ colorScheme: scheme })
    const page = await context.newPage()
    await page.goto('/')
    await expect(page.getByRole('status')).toHaveText(/연결됨/)
    await expect(page).toHaveScreenshot(`app-${scheme}.png`, { maxDiffPixels: 100 })
    await context.close()
  })
}
