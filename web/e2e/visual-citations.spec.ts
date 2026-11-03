import { existsSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'

// 시각 회귀(M5-10): 일지 상세의 인용 구역(시안 일지 03)·노트의 인용 번호(일지 04)와 답변 말풍선의
// 출처 칩(시안 대화 05)을 라이트·다크로 기준 이미지와 비교한다. 서버 응답은 고정한 값으로 바꿔
// 날짜·DB 상태에 흔들리지 않게 한다. 기준 이미지가 없는 OS에서는 건너뛴다(visual.spec.ts와 같은 규칙).
// 만들거나 갱신하려면 `npx playwright test e2e/visual-citations.spec.ts --update-snapshots=all`을
// 실행하고 눈으로 확인한 뒤 커밋한다.

const SESSION = {
  id: 'v-cite',
  date: '2026-10-21',
  started_at: '2026-10-21T01:10:00Z',
  ended_at: '2026-10-21T01:32:00Z',
  status: 'ended',
  title: '산책 중 날씨 알림 앱 구상',
  summary: [
    '**비 오기 30분 전에 알려 주는 날씨 알림을 붙이기로 했다.**',
    '기상청 동네예보는 시간 단위로 강수 확률을 준다.',
    '바람이 센 능선에서는 소리 알림이 잘 안 들린다.',
  ],
  tags: ['산책', '날씨'],
  journal_status: 'done',
  counts: { idea: 1, todo: 0, memo: 1 },
}

const DETAIL = {
  session: SESSION,
  summary_cites: [[1], [1], [2]],
  citations: [
    { n: 1, title: '기상청 날씨누리 · 동네예보', url: 'https://www.weather.go.kr/forecast' },
    { n: 2, title: '등산 안전 가이드 · 바람', url: 'https://www.knps.or.kr/guide/wind' },
  ],
  checks: ['동네예보 API의 무료 호출 한도가 충분한지(확인 필요)'],
  persona_name: '제니',
  notes: [
    {
      id: 'n1',
      kind: 'idea',
      content: '비 오기 30분 전에 알려 주는 날씨 알림',
      starred: true,
      done: false,
      created_at: '2026-10-21T01:20:00Z',
      cites: [],
    },
    {
      id: 'n2',
      kind: 'memo',
      content: '바람이 센 능선에서는 소리 알림이 잘 안 들린다',
      starred: false,
      done: false,
      created_at: '2026-10-21T01:25:00Z',
      cites: [2],
    },
  ],
  turns: [
    {
      id: 't1',
      seq: 0,
      role: 'assistant',
      text: '안녕하세요. 오늘은 무슨 이야기를 해 볼까요?',
      interrupted: false,
      merged_from: null,
      created_at: '2026-10-21T01:10:00Z',
      attachments: [],
      sources: [],
    },
  ],
}

const STARTED = {
  session: {
    id: 'v-chat',
    mode: 'text',
    status: 'active',
    started_at: '2026-10-21T01:10:00Z',
    ended_at: null,
  },
  greeting: { turn_id: 'g1', text: '안녕하세요! 오늘은 어떤 생각을 하며 걸어요?', audio: null },
  persona: { id: 'jenny', name: '제니', ack: [] },
}

const tool = (phase: string, extra: object = {}) => ({
  type: 'tool',
  phase,
  tool_use_id: 't1',
  name: 'web_search',
  input: null,
  summary: null,
  is_error: false,
  notice: null,
  ...extra,
})

const REPLY_EVENTS = [
  { type: 'turn', turn_id: 'a1' },
  tool('start'),
  tool('call', { input: { query: '서울 오늘 날씨' } }),
  tool('end', {
    summary: {
      kind: 'web_search',
      query: '서울 오늘 날씨',
      links: [],
      sources: ['weather.naver.com', 'kma.go.kr'],
    },
  }),
  {
    type: 'sentence',
    index: 0,
    text: '서울은 오늘 맑고 낮 기온이 18도예요.',
    audio: null,
    speech_text: null,
  },
  {
    type: 'sentence',
    index: 1,
    text: '저녁에는 구름이 조금 껴요.',
    audio: null,
    speech_text: null,
  },
  {
    type: 'done',
    turn_id: 'a1',
    text: '서울은 오늘 맑고 낮 기온이 18도예요. 저녁에는 구름이 조금 껴요.',
    interrupted: false,
    session_status: 'active',
    superseded: false,
  },
]

async function mockApi(page: Page) {
  await page.route('**/api/notes/open-ideas*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/journal', (route) => route.fulfill({ json: [SESSION] }))
  await page.route('**/api/journal/v-cite', (route) => route.fulfill({ json: DETAIL }))
  await page.route('**/api/usage', (route) =>
    route.fulfill({ json: { status: null, five_hour: null, seven_day: null, updated_at: null } }),
  )
  await page.route('**/api/sessions', (route) =>
    route.request().method() === 'POST'
      ? route.fulfill({ status: 201, json: STARTED })
      : route.fallback(),
  )
  await page.route('**/api/sessions/v-chat/turns', (route) =>
    route.fulfill({
      headers: { 'Content-Type': 'text/event-stream' },
      body: REPLY_EVENTS.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),
    }),
  )
}

for (const scheme of ['light', 'dark'] as const) {
  const screens: [string, (page: Page) => Promise<void>][] = [
    [
      'journal-citations',
      async (page) => {
        await page.goto('/journal/v-cite')
        await expect(page.getByRole('region', { name: '결론' })).toBeVisible()
        await page.getByRole('region', { name: '인용' }).scrollIntoViewIfNeeded()
        await expect(page.getByRole('region', { name: '인용' })).toContainText('[2]')
      },
    ],
    [
      'journal-notes-cites',
      async (page) => {
        await page.goto('/journal/v-cite')
        await expect(page.getByRole('region', { name: '메모' })).toBeVisible()
        await page.getByRole('region', { name: '메모' }).scrollIntoViewIfNeeded()
      },
    ],
    [
      'chat-sources',
      async (page) => {
        await page.goto('/')
        await page.getByRole('button', { name: '글로 대화 시작' }).click()
        await page.getByRole('textbox', { name: '메시지' }).fill('오늘 서울 날씨 검색해서 알려 줘.')
        await page.getByRole('button', { name: '보내기' }).click()
        await expect(page.getByRole('list', { name: '출처' })).toBeVisible()
      },
    ],
  ]
  for (const [name, open] of screens) {
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
      await open(page)
      await page.evaluate('document.fonts.ready')
      await expect(page).toHaveScreenshot(`${name}-${scheme}.png`, { maxDiffPixels: 150 })
      await context.close()
    })
  }
}
