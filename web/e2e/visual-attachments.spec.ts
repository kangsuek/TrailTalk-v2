import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

// 시각 회귀(M5-08): 글 대화의 첨부 선택 상태(대화 09)와 일지 전문의 첨부 썸네일·칩(일지 05)을 라이트·다크로
// 기준 이미지와 비교한다. 서버 응답은 고정한 값으로 바꿔 DB 상태에 흔들리지 않게 한다(visual-journal과 같다).
// 기준 이미지가 없는 OS에서는 건너뛴다. 만들거나 갱신하려면 `npx playwright test e2e/visual-attachments.spec.ts
// --update-snapshots=all`을 실행하고 눈으로 확인한 뒤 커밋한다.

const FIXTURES = resolve(import.meta.dirname, 'fixtures')
const PNG = resolve(FIXTURES, 'trail-map.png')
const TXT = resolve(FIXTURES, 'course-memo.txt')

const STARTED = {
  session: {
    id: 'v-chat',
    mode: 'text',
    status: 'active',
    started_at: '2026-11-03T01:00:00Z',
    ended_at: null,
  },
  greeting: { turn_id: 'g1', text: '안녕하세요! 오늘은 어떤 이야기를 해 볼까요?', audio: null },
  persona: { id: 'jenny', name: '제니', ack: [] },
}

const REPLY = [
  { type: 'turn', turn_id: 'a1' },
  {
    type: 'sentence',
    index: 0,
    text: '지도를 보니 약수터 앞 평지와 능선 전망대가 쉬기 좋아 보여요.',
    audio: null,
    speech_text: null,
  },
  {
    type: 'done',
    turn_id: 'a1',
    text: '지도를 보니 약수터 앞 평지와 능선 전망대가 쉬기 좋아 보여요.',
    interrupted: false,
    session_status: 'active',
    superseded: false,
  },
]

const counts = { idea: 0, todo: 0, memo: 0 }
const SESSION = {
  id: 'v-att',
  date: '2026-11-03',
  started_at: '2026-11-03T01:10:00Z',
  ended_at: '2026-11-03T01:32:00Z',
  status: 'ended',
  title: '쉬어 갈 만한 곳 고르기',
  summary: ['**능선 전망대에서 쉬어 가기로 했다.**'],
  tags: ['등산로'],
  journal_status: 'done',
  counts,
}
const turn = (id: string, seq: number, role: string, text: string, attachments: object[] = []) => ({
  id,
  seq,
  role,
  text,
  interrupted: false,
  merged_from: null,
  created_at: `2026-11-03T01:1${seq}:00Z`,
  attachments,
})
const DETAIL = {
  session: SESSION,
  summary_cites: [[]],
  citations: [],
  checks: [],
  persona_name: '제니',
  notes: [],
  turns: [
    turn('t1', 0, 'assistant', '안녕하세요! 오늘은 어떤 이야기를 해 볼까요?'),
    turn('t2', 1, 'user', '이 등산로 지도에서 쉬어 갈 만한 곳 세 군데만 골라 줘.', [
      { id: 'img1', name: 'trail-map.png', mime: 'image/jpeg', size: 1600, thumb: true },
      { id: 'txt1', name: '코스-메모.txt', mime: 'text/plain', size: 90, thumb: false },
      { id: 'pdf1', name: '등산로-안내.pdf', mime: 'application/pdf', size: 600, thumb: false },
    ]),
    turn('t3', 2, 'assistant', '지도를 보니 약수터 앞 평지와 능선 전망대가 쉬기 좋아 보여요.'),
  ],
}

async function mockApi(page: Page) {
  await page.route('**/api/notes/open-ideas*', (route) => route.fulfill({ json: [] }))
  await page.route('**/api/usage', (route) =>
    route.fulfill({ json: { status: null, five_hour: null, seven_day: null, updated_at: null } }),
  )
  await page.route('**/api/sessions', (route) => route.fulfill({ json: STARTED, status: 201 }))
  await page.route('**/api/sessions/v-chat/turns/files', (route) =>
    route.fulfill({
      status: 200,
      headers: { 'Content-Type': 'text/event-stream' },
      body: REPLY.map((e) => `event: ${e.type}\ndata: ${JSON.stringify(e)}\n\n`).join(''),
    }),
  )
  await page.route('**/api/journal/v-att', (route) => route.fulfill({ json: DETAIL }))
  await page.route('**/api/attachments/img1*', (route) =>
    route.fulfill({ body: readFileSync(PNG), contentType: 'image/png' }),
  )
}

for (const scheme of ['light', 'dark'] as const) {
  const shots: [string, (page: Page) => Promise<void>][] = [
    [
      'chat-attach',
      async (page) => {
        await page.goto('/')
        await page.getByRole('button', { name: '글로 대화 시작' }).click()
        await expect(page.getByText(STARTED.greeting.text)).toBeVisible({ timeout: 15_000 })
        // 보낸 첨부(말풍선 썸네일)와 새로 고른 첨부(입력창 칩)가 함께 보이는 화면
        const picker = page.locator('input[type=file]')
        await picker.setInputFiles([PNG])
        await page
          .getByRole('textbox', { name: '메시지' })
          .fill('이 등산로 지도에서 쉬어 갈 만한 곳 세 군데만 골라 줘.')
        await page.getByRole('button', { name: '보내기' }).click()
        await expect(page.getByText('능선 전망대가 쉬기 좋아 보여요.')).toBeVisible()
        await picker.setInputFiles([PNG, TXT])
        await page
          .getByRole('textbox', { name: '메시지' })
          .fill('전망대로 가 볼까 하는데\n시간은 얼마나 걸릴까?')
        await expect(page.getByRole('list', { name: '보낼 첨부' })).toContainText('course-memo.txt')
      },
    ],
    [
      'journal-transcript-attach',
      async (page) => {
        await page.goto('/journal/v-att')
        await expect(page.getByRole('region', { name: '결론' })).toBeVisible()
        await page.getByRole('button', { name: /전문/ }).click()
        const thumb = page.getByRole('list', { name: '전문' }).getByAltText('trail-map.png')
        await expect(thumb).toBeVisible()
        await expect
          .poll(() =>
            thumb.evaluate((img) => (img as unknown as { naturalWidth: number }).naturalWidth),
          )
          .toBeGreaterThan(0)
        // 첨부가 든 말풍선이 화면에 다 들어오게 위쪽으로 맞춘다
        await page.locator('.t-user').evaluate((el) => el.scrollIntoView({ block: 'center' }))
      },
    ],
  ]
  for (const [name, prepare] of shots) {
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
      await prepare(page)
      await page.evaluate('document.fonts.ready')
      await expect(page).toHaveScreenshot(`${name}-${scheme}.png`, { maxDiffPixels: 150 })
      await context.close()
    })
  }
}
