import { expect, test } from '@playwright/test'
import { sessionCount } from './db.ts'
import { API_PORT } from './ports.ts'

// CSRF 방어(D3, 계약 1.5)를 실제 브라우저에서 확인한다. 다른 출처(localhost:4999)의 페이지가 이 사용자의
// 브라우저로 서버 API를 두드려도 상태가 바뀌지 않아야 한다. 같은 출처의 앱 화면이 보내는 요청은
// 다른 E2E 시험이 모두 쓰므로(헤더를 붙이는 api/http.ts) 여기서는 막는 쪽만 본다.
const API = `http://127.0.0.1:${API_PORT}`
// 허용 목록에 없는 다른 출처(로컬). 브라우저가 교차 출처 요청을 서버에 닿기 전에 막는 경우가 있어
// 서버 쪽 거절은 server/tests/test_csrf.py와 아래 '헤더가 없는 직접 요청' 시험이 직접 확인한다
const EVIL = 'http://localhost:4999/'

test.describe('CSRF 방어', () => {
  test('다른 출처 페이지의 단순 요청과 사용자 정의 헤더 요청이 모두 상태를 바꾸지 못한다', async ({
    page,
    request,
  }) => {
    const nicknameBefore = (await (await request.get('/api/profile')).json()).nickname
    const sessionsBefore = sessionCount()
    await page.route(`${EVIL}**`, (route) =>
      route.fulfill({ contentType: 'text/html', body: '<html><body>evil</body></html>' }),
    )
    await page.goto(EVIL)

    // ① 사전 요청 없이 나가는 단순 요청(POST, text/plain 본문, 사용자 정의 헤더 없음): 서버가 거절한다.
    //    (브라우저는 no-cors에서 PUT·DELETE를 보내지 못해 단순 요청은 GET·HEAD·POST뿐이다)
    await page.evaluate(
      (api) =>
        fetch(`${api}/api/sessions`, {
          method: 'POST',
          mode: 'no-cors',
          headers: { 'Content-Type': 'text/plain' },
          body: JSON.stringify({ mode: 'text' }),
        }).catch(() => 'blocked'), // 브라우저가 먼저 막아도, 서버가 거절해도 결과(상태 불변)는 같다
      API,
    )
    // ② 헤더를 붙이면 사전 요청(OPTIONS)이 필요한데 서버는 CORS를 열지 않아 브라우저가 막는다
    const blocked = await page.evaluate(
      (api) =>
        fetch(`${api}/api/profile`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', 'X-TrailTalk': '1' },
          body: JSON.stringify({ nickname: '해커' }),
        }).then(
          () => 'sent',
          () => 'blocked',
        ),
      API,
    )
    expect(blocked).toBe('blocked')
    // ③ <form> 제출(urlencoded)
    await page.setContent(
      `<iframe name="sink"></iframe>` +
        `<form method="POST" action="${API}/api/sessions" target="sink"><input name="mode" value="text"></form>`,
    )
    await page.locator('form').evaluate((form) => (form as unknown as { submit(): void }).submit())
    await page.waitForTimeout(500)

    const nicknameAfter = (await (await request.get('/api/profile')).json()).nickname
    expect(nicknameAfter).toBe(nicknameBefore)
    expect(nicknameAfter).not.toBe('해커')
    expect(sessionCount()).toBe(sessionsBefore) // 세션이 하나도 만들어지지 않았다
  })

  test('헤더가 없는 직접 요청은 403 csrf_rejected다', async ({ request }) => {
    const response = await request.put('/api/profile', { data: { nickname: '해커' } })
    expect(response.status()).toBe(403)
    expect((await response.json()).error.code).toBe('csrf_rejected')
  })
})
