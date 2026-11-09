import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { PREVIEW_PORT } from './ports.ts'

// e2e 타입에는 DOM이 없어, 브라우저에서 도는 콜백이 쓰는 서비스 워커·캐시 모양만 적는다
declare const caches: {
  keys(): Promise<string[]>
  open(name: string): Promise<{ keys(): Promise<{ url: string }[]> }>
}
interface SwContainer {
  ready: Promise<unknown>
  controller: unknown
  getRegistration(): Promise<{ update(): Promise<unknown> } | undefined>
}

// PWA(M6)를 운영 빌드(vite preview)에서 실제 브라우저로 확인한다: 서비스 워커 등록, 오프라인 앱 껍데기,
// 새 버전은 자동 적용 없이 설정 화면의 "적용" 버튼으로만 바뀐다(Spec 8절, 시안 설정 03).
test.use({ baseURL: `http://127.0.0.1:${PREVIEW_PORT}` })

async function controlled(page: Page) {
  await page.goto('/')
  await page.evaluate(
    () => (navigator as unknown as { serviceWorker: SwContainer }).serviceWorker.ready,
  )
  // 처음 설치된 워커가 이 페이지를 제어할 때까지(clients.claim) 기다린다
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          (navigator as unknown as { serviceWorker: SwContainer }).serviceWorker.controller !==
          null,
      ),
    )
    .toBe(true)
}

const versionOf = (page: Page) =>
  page.evaluate(async () => (await caches.keys()).filter((k) => k.startsWith('trailtalk-')))

test.describe('PWA', () => {
  test('매니페스트와 아이콘이 있고 서비스 워커가 앱 껍데기를 미리 저장한다', async ({
    page,
    request,
  }) => {
    const manifest = await (await request.get('/manifest.webmanifest')).json()
    expect(manifest).toMatchObject({
      short_name: 'TrailTalk',
      display: 'standalone',
      start_url: '/',
    })
    expect((await request.get(manifest.icons[0].src)).status()).toBe(200)

    await controlled(page)
    const [name] = await versionOf(page)
    expect(name).toMatch(/^trailtalk-[0-9a-f]{12}$/)
    const cached = await page.evaluate(async (cache) => {
      const keys = await (await caches.open(cache)).keys()
      return keys.map((r) => new URL(r.url).pathname)
    }, name)
    expect(cached).toEqual(expect.arrayContaining(['/index.html', '/manifest.webmanifest']))
    // 서버 API는 저장하지 않는다
    expect(cached.some((path: string) => path.startsWith('/api/'))).toBe(false)
  })

  test('오프라인에서 새로고침해도 앱이 열리고 서버가 안 닿는다고 알려 준다', async ({
    page,
    context,
  }) => {
    await controlled(page)
    await context.setOffline(true)
    await page.reload()
    await expect(page.getByRole('button', { name: '글로 대화 시작' })).toBeVisible()
    // 화면 경로로 바로 들어와도 앱 껍데기는 열리고, 서버가 필요한 부분만 오류를 보인다
    await page.goto('/journal/no-such-session')
    await expect(page.getByText('서버에 연결할 수 없어요.')).toBeVisible()
    await context.setOffline(false)
  })

  test('새 버전은 자동으로 바뀌지 않고 설정의 적용 버튼으로만 바뀐다', async ({ page }) => {
    await controlled(page)
    const [before] = await versionOf(page)

    // 새 빌드를 흉내 낸다: 미리보기 서버가 내려 주는 dist/sw.js의 버전만 바꾼다(그러면 브라우저가 새
    // 워커를 설치한다). 시험이 끝나면 반드시 되돌린다
    const swPath = resolve(import.meta.dirname, '../dist/sw.js')
    const original = readFileSync(swPath, 'utf8')
    writeFileSync(
      swPath,
      original.replace(/const VERSION = '[0-9a-f]+'/, "const VERSION = 'e2enewbuild01'"),
    )
    try {
      await page.getByRole('button', { name: '설정' }).click()
      await expect(page.getByLabel('호칭')).toBeVisible()
      await page.evaluate(async () => {
        const container = (navigator as unknown as { serviceWorker: SwContainer }).serviceWorker
        const registration = await container.getRegistration()
        await registration?.update()
      })

      const notice = page.getByRole('status').filter({ hasText: '새 버전이 있어요' })
      await expect(notice).toBeVisible()
      await expect(notice).toContainText('대화가 끝난 뒤에 적용하는 게 좋아요')
      // 시안 설정 03(라이트·다크)의 안내 박스와 눈으로 대조하는 시각 기준
      const appSection = page.getByRole('region', { name: '앱 정보' })
      await page.emulateMedia({ colorScheme: 'light' })
      await expect(appSection).toHaveScreenshot('settings-update-light.png')
      await page.emulateMedia({ colorScheme: 'dark' })
      await expect(appSection).toHaveScreenshot('settings-update-dark.png')
      await page.emulateMedia({ colorScheme: 'light' })
      // 안내만 떴을 뿐 아직 옛 버전이 제어한다(자동으로 바뀌지 않았다)
      expect(await versionOf(page)).toContain(before)
      expect(await page.title()).toBe('TrailTalk')

      await notice.getByRole('button', { name: '적용' }).click()
      // 새 워커가 제어를 넘겨받고 화면이 새로 고쳐지면 안내가 사라지고 옛 캐시는 지워진다
      await expect
        .poll(async () => {
          try {
            return (await versionOf(page)).join(',')
          } catch {
            return 'reloading' // 적용하면 화면이 한 번 새로 고쳐진다
          }
        })
        .toBe('trailtalk-e2enewbuild01')
      await page.getByRole('button', { name: '설정' }).click()
      await expect(page.getByLabel('호칭')).toBeVisible()
      await expect(page.getByText('새 버전이 있어요')).toHaveCount(0)
    } finally {
      writeFileSync(swPath, original) // dist를 원래대로(다른 시험·미리보기가 새 버전을 보지 않게)
    }
  })
})
