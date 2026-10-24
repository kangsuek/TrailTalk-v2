import { expect, test, type Page } from '@playwright/test'
import { latestSession, turnsOf } from './db.ts'

// 격리 서버(임시 DB, 가짜 Claude CLI)와 웹 개발 서버로 글 대화를 브라우저에서 실제로 해 본다.
// 가짜 CLI는 첫 사용자 메시지에 save_note 도구를 쓰는 녹화 턴을 내고, "__say__:글" 같은 지시어를
// 쓰면 그 글을 답한다. 서버 기록은 임시 DB를 직접 읽어 확인한다.
// 같은 서버·DB를 모든 시험이 쓰므로 시험마다 새 대화를 시작하고 그 세션의 기록만 본다.

async function startConversation(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: '글로 대화 시작' }).click()
  await expect(page.getByRole('list', { name: '대화 내용' })).toBeVisible()
}

async function send(page: Page, text: string) {
  await page.getByRole('textbox', { name: '메시지' }).fill(text)
  await page.getByRole('button', { name: '보내기' }).click()
}

test.describe('글 대화', () => {
  test('인사말을 받고, 도구 알림과 답변이 보이고, 서버 DB에 기록된다', async ({ page }) => {
    await startConversation(page)
    const messages = page.getByRole('list', { name: '대화 내용' })
    await expect(messages.getByRole('listitem').first()).toContainText('안녕하세요')
    const who = page.locator('.chat-name')
    await expect(who).toHaveText(/\S/) // 캐릭터 이름은 서버(YAML)에서 온다

    // 녹화된 첫 사용자 턴: save_note(idea) 도구를 부르고 저장했다고 답한다
    await send(page, '등산로 쓰레기통 지도 아이디어를 저장해줘')
    await expect(messages).toContainText('아이디어 저장: 등산로에 쓰레기통 지도를 만드는 아이디어')
    await expect(messages).toContainText('노트에 저장해뒀어요')
    await expect(page.getByRole('textbox', { name: '메시지' })).toHaveValue('')

    const session = latestSession()
    const turns = turnsOf(session.id)
    expect(turns.map((t) => [t.seq, t.role])).toEqual([
      [0, 'assistant'],
      [1, 'user'],
      [2, 'assistant'],
    ])
    expect(turns[0].greeting).toBe(1)
    expect(turns[1].text).toBe('등산로 쓰레기통 지도 아이디어를 저장해줘')
    expect(turns[2].text).toContain('노트에 저장해뒀어요')
    expect(turns[2].interrupted).toBe(0)
  })

  test('여러 문장 답변은 한 말풍선에 이어 보이고 그대로 저장된다', async ({ page }) => {
    await startConversation(page)
    await send(page, '__say__:첫 문장입니다. 둘째 문장이에요. 셋째 문장이죠.')
    const reply = page.locator('.bubble-assistant').last()
    await expect(reply).toHaveText('첫 문장입니다. 둘째 문장이에요. 셋째 문장이죠.')
    await expect(reply).toHaveAttribute('data-status', 'done')
    const turns = turnsOf(latestSession().id)
    expect(turns.at(-1)?.text).toBe('첫 문장입니다. 둘째 문장이에요. 셋째 문장이죠.')
    expect(turns.at(-1)?.interrupted).toBe(0)
  })

  test('답변 도중 새로고침해도 서버는 받은 문장까지 기록하고 끊긴 답변으로 남긴다', async ({
    page,
  }) => {
    await startConversation(page)
    // 두 문장을 보낸 뒤 CLI가 멈춘다(__say_then_hang__)
    await send(page, '__say_then_hang__:첫 문장입니다. 둘째 문장이에요. 셋째 문장이죠.')
    await expect(page.locator('.bubble-assistant').last()).toContainText('첫 문장입니다.')
    const sessionId = latestSession().id
    await page.reload()
    // 새로고침하면 화면은 처음으로 돌아가지만(대화 복원은 M2 일지) 서버 기록은 남는다
    await expect(page.getByRole('button', { name: '글로 대화 시작' })).toBeVisible()
    await expect
      .poll(() => turnsOf(sessionId).at(-1), { timeout: 15_000 })
      .toMatchObject({ role: 'assistant', interrupted: 1 })
    const reply = turnsOf(sessionId).at(-1)!
    expect(reply.text.startsWith('첫 문장입니다.')).toBe(true)
    expect(reply.text).not.toContain('셋째 문장이죠.')
    expect(turnsOf(sessionId)[1]).toMatchObject({ role: 'user' })
  })

  test('CLI가 죽으면 오류를 보이고, 다음 메시지는 맥락을 이어 정상 답한다', async ({ page }) => {
    await startConversation(page)
    await send(page, '__crash__')
    await expect(page.getByRole('alert')).toContainText('연결이 끊겼어요')
    await expect(page.getByText('답변이 끊겼어요')).toBeVisible()
    await send(page, '__say__:다시 왔어요.')
    await expect(page.getByRole('list', { name: '대화 내용' })).toContainText('다시 왔어요.')
    await expect(page.getByRole('alert')).toHaveCount(0)
  })

  test('탭을 바꿔도 진행 중인 대화가 남는다', async ({ page }) => {
    await startConversation(page)
    await send(page, '__say__:탭을 옮겨도 남아요.')
    await expect(page.getByRole('list', { name: '대화 내용' })).toContainText('탭을 옮겨도 남아요.')
    const nav = page.getByRole('navigation', { name: '메인 메뉴' })
    await nav.getByRole('button', { name: '일지' }).click()
    await expect(page.getByText('일지 화면은 준비 중입니다.')).toBeVisible()
    await expect(page.getByRole('list', { name: '대화 내용' })).toBeHidden()
    await nav.getByRole('button', { name: '대화' }).click()
    await expect(page.getByRole('list', { name: '대화 내용' })).toContainText('탭을 옮겨도 남아요.')
  })

  test('대화종료를 누르면 마무리 멘트가 보이고 서버 세션이 끝나며 새 대화를 시작할 수 있다', async ({
    page,
  }) => {
    await startConversation(page)
    const sessionId = latestSession().id
    await page.getByRole('button', { name: '대화종료' }).click()
    await expect(page.getByText('대화 끝남')).toBeVisible()
    const messages = page.getByRole('list', { name: '대화 내용' })
    await expect(messages.getByRole('listitem')).toHaveCount(2) // 인사말 + 마무리 멘트
    expect(latestSession()).toMatchObject({ id: sessionId, status: 'ended' })
    expect(latestSession().ended_at).not.toBeNull()

    await page.getByRole('button', { name: '새 대화 시작' }).click()
    await expect(messages.getByRole('listitem')).toHaveCount(1)
    expect(latestSession().id).not.toBe(sessionId)
  })
})
