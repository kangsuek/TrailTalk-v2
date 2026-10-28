import { existsSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

// 시각 회귀(M2): 대화 시작·일지 목록·일지 상세를 라이트·다크로 기준 이미지와 비교한다.
// 서버 응답은 고정한 값으로 바꿔 날짜·DB 상태에 흔들리지 않게 한다. 기준 이미지가 없는 OS에서는
// 건너뛴다(visual.spec.ts와 같은 규칙). 만들거나 갱신하려면 `npm run e2e:update`를 실행하고
// 눈으로 확인한 뒤 커밋한다.

const counts = (idea: number, todo: number, memo: number) => ({ idea, todo, memo })

const ITEMS = [
  {
    id: 'v-active',
    date: '2026-10-22',
    started_at: '2026-10-22T05:40:00Z',
    ended_at: null,
    status: 'active',
    title: null,
    summary: [],
    tags: [],
    journal_status: null,
    counts: counts(0, 0, 0),
  },
  {
    id: 'v-done',
    date: '2026-10-21',
    started_at: '2026-10-21T01:10:00Z',
    ended_at: '2026-10-21T01:32:00Z',
    status: 'ended',
    title: '산책 코스에 맞춰 날씨 알림을 붙이면 어떨까',
    summary: ['**산책 코스에 날씨 알림을 붙이는 방향으로 가 보기로 했다.**', '출발 한 시간 전에 비 소식을 알려 주는 정도가 부담이 적다.'],
    tags: ['산책', '날씨'],
    journal_status: 'done',
    counts: counts(2, 1, 0),
  },
  {
    id: 'v-failed',
    date: '2026-10-21',
    started_at: '2026-10-21T00:20:00Z',
    ended_at: '2026-10-21T00:30:00Z',
    status: 'ended',
    title: '걸음 수 대신 오늘 떠오른 생각 수를 세 보기',
    summary: [],
    tags: [],
    journal_status: 'failed',
    counts: counts(0, 0, 0),
  },
  {
    id: 'v-old',
    date: '2026-10-19',
    started_at: '2026-10-19T09:00:00Z',
    ended_at: '2026-10-19T09:20:00Z',
    status: 'ended',
    title: '주말 북한산 코스 정하기',
    summary: ['**우이동 입구에서 출발하는 코스로 정했다.**'],
    tags: ['북한산'],
    journal_status: 'done',
    counts: counts(1, 0, 1),
  },
]

const DETAIL = {
  session: ITEMS[1],
  summary_cites: [[], []],
  citations: [],
  checks: ['날씨 API의 무료 호출 한도가 충분한지(확인 필요)'],
  persona_name: '제니',
  notes: [
    {
      id: 'n1',
      kind: 'idea',
      content: '산책 코스를 고르면 **출발 한 시간 전** 날씨 알림을 보낸다',
      starred: true,
      done: false,
      created_at: '2026-10-21T01:20:00Z',
      cites: [],
    },
    {
      id: 'n2',
      kind: 'idea',
      content: '비 오는 날에는 대신 갈 만한 실내 코스를 추천한다',
      starred: false,
      done: false,
      created_at: '2026-10-21T01:22:00Z',
      cites: [],
    },
    {
      id: 'n3',
      kind: 'todo',
      content: '이번 주말에 날씨 API 두 곳의 무료 한도를 비교하기',
      starred: false,
      done: false,
      created_at: '2026-10-21T01:25:00Z',
      cites: [],
    },
  ],
  turns: [
    { id: 't1', seq: 0, role: 'assistant', text: '안녕하세요. 오늘은 무슨 이야기를 해 볼까요?', interrupted: false, merged_from: null, created_at: '2026-10-21T01:10:00Z', attachments: [] },
    { id: 't2', seq: 1, role: 'user', text: '산책 코스에 날씨 알림을 붙이면 어떨까 해요.', interrupted: false, merged_from: null, created_at: '2026-10-21T01:11:00Z', attachments: [] },
  ],
}

const OPEN_IDEAS = [
  { id: 'i1', content: '산책 코스에 맞춰 날씨 알림을 붙이면 어떨까', starred: true, session_id: 'v-done', created_at: '2026-10-21T01:20:00Z', counts: counts(2, 1, 0) },
  { id: 'i2', content: '걸음 수 대신 오늘 떠오른 생각 수를 세 보기', starred: false, session_id: 'v-failed', created_at: '2026-10-21T00:25:00Z', counts: counts(3, 0, 1) },
]

async function mockApi(page: Page) {
  await page.route('**/api/notes/open-ideas*', (route) => route.fulfill({ json: OPEN_IDEAS }))
  await page.route('**/api/journal', (route) => route.fulfill({ json: ITEMS }))
  await page.route('**/api/journal/v-done', (route) => route.fulfill({ json: DETAIL }))
}

for (const scheme of ['light', 'dark'] as const) {
  const screens: [string, string, (page: Page) => Promise<void>][] = [
    ['conversation-start', '/', async (page) => expect(page.getByText('지난 아이디어 이어 가기')).toBeVisible()],
    ['journal-list', '/journal', async (page) => expect(page.getByText('주말 북한산 코스 정하기')).toBeVisible()],
    ['journal-detail', '/journal/v-done', async (page) => expect(page.getByRole('region', { name: '결론' })).toBeVisible()],
  ]
  for (const [name, url, ready] of screens) {
    test(`${name}(${scheme})`, async ({ browser }, testInfo) => {
      const baseline = testInfo.snapshotPath(`${name}-${scheme}.png`)
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
      await mockApi(page)
      await page.goto(url)
      await ready(page)
      await page.evaluate(() => document.fonts.ready)
      await expect(page).toHaveScreenshot(`${name}-${scheme}.png`, { maxDiffPixels: 150 })
      await context.close()
    })
  }
}
