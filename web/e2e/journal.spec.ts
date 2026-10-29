import { expect, test, type Page } from '@playwright/test'
import { latestSession } from './db.ts'

// 일지 화면 E2E: 가짜 CLI(녹화 재생) 격리 서버로 대화 종료 → 정리 → 목록·상세, 노트·제목 수정, 삭제,
// 다시 열기, 새로고침 복원을 브라우저에서 실제로 해 본다. 일지 정리(단발 호출)는 추출 녹화 한 줄을 낸다
// (title "등산로 쓰레기통 지도 아이디어"). 같은 서버·DB를 모든 시험이 쓰므로 시험마다 새 대화를 만들고
// 그 세션 ID의 상세 경로(/journal/:id)로 간다.

const EXTRACT_TITLE = '등산로 쓰레기통 지도 아이디어'

async function send(page: Page, text: string) {
  await page.getByRole('textbox', { name: '메시지' }).fill(text)
  await page.getByRole('button', { name: '보내기' }).click()
}

/** 새 글 대화를 시작해 한 번 주고받고 끝낸 뒤, 정리가 끝난 일지 상세를 열어 세션 ID를 돌려준다. */
async function endedJournal(page: Page): Promise<string> {
  await page.goto('/')
  await page.getByRole('button', { name: '글로 대화 시작' }).click()
  const messages = page.getByRole('list', { name: '대화 내용' })
  await expect(messages).toBeVisible()
  await send(page, '등산로 쓰레기통 지도 아이디어를 저장해줘')
  await expect(messages).toContainText('노트에 저장해뒀어요')
  const sessionId = latestSession().id
  await page.getByRole('button', { name: '대화종료' }).click()
  await page.getByRole('button', { name: '끝내고 정리하기' }).click()
  await expect(page.getByText('대화 끝남')).toBeVisible()
  await openDetail(page, sessionId)
  return sessionId
}

async function openDetail(page: Page, sessionId: string) {
  await page.goto(`/journal/${sessionId}`)
  // 정리는 서버가 뒤에서 하므로 끝날 때까지 상세가 스스로 갱신된다
  await expect(page.getByRole('region', { name: '결론' })).toBeVisible({ timeout: 20_000 })
}

test.describe('일지', () => {
  test('대화를 끝내면 정리되어 목록에 뜨고 상세에 요약·노트·태그가 보인다', async ({ page }) => {
    const sessionId = await endedJournal(page)
    const conclusion = page.getByRole('region', { name: '결론' })
    await expect(conclusion).toContainText('등산로 쓰레기통 위치를 지도로 보여 주는 앱')
    await expect(page.getByRole('region', { name: '알게 된 것' })).toContainText('쓰레기통 지도')
    await expect(page.getByRole('region', { name: '확인할 것' })).toContainText('공개 데이터')
    await expect(page.getByRole('region', { name: '할 일' })).toContainText('북한산 입구')
    await expect(page.getByRole('region', { name: '메모' })).toContainText('정상에는 쓰레기통이 없다')
    await expect(page.getByRole('list', { name: '태그' })).toContainText('지도 앱')

    // 목록: 오늘 묶음에 제목과 저장 개수가 보인다
    await page.getByRole('button', { name: '목록으로' }).click()
    await expect(page.getByRole('heading', { name: '일지', level: 1 })).toBeVisible()
    const card = page.getByRole('button', { name: new RegExp(EXTRACT_TITLE) }).first()
    await expect(card).toContainText('아이디어')
    await expect(card).toContainText('할 일 1')
    // 가장 최근 대화가 맨 위이므로 이 대화의 카드다
    await card.click()
    await expect(page).toHaveURL(new RegExp(`/journal/${sessionId}$`))
  })

  test('노트를 고쳐 저장하면 새로고침해도 남는다', async ({ page }) => {
    await endedJournal(page)
    await page.getByRole('button', { name: '메모 수정' }).click()
    const box = page.getByRole('textbox', { name: '메모 내용' })
    await box.fill('북한산 정상 쓰레기통은 입구에만 있다')
    await page.getByRole('button', { name: '저장', exact: true }).click()
    const memos = page.getByRole('region', { name: '메모' })
    await expect(memos).toContainText('입구에만 있다')
    await page.reload()
    await expect(page.getByRole('region', { name: '메모' })).toContainText('입구에만 있다')
  })

  test('제목을 고치면 목록에 새 제목이 보인다', async ({ page }) => {
    await endedJournal(page)
    await page.getByRole('button', { name: '더 보기' }).click()
    await page.getByRole('menuitem', { name: '제목 수정' }).click()
    const field = page.getByRole('textbox', { name: '대화 제목' })
    const newTitle = `쓰레기통 지도 구상 ${Date.now()}`
    await field.fill(newTitle)
    await page.getByRole('button', { name: '저장', exact: true }).click()
    await expect(page.getByRole('dialog', { name: '제목 수정' })).toHaveCount(0)
    await page.getByRole('button', { name: '목록으로' }).click()
    await expect(page.getByRole('button', { name: new RegExp(newTitle) })).toHaveCount(1)
  })

  test('대화를 지우면 목록에서 사라지고 상세는 없는 대화로 안내한다', async ({ page }) => {
    const sessionId = await endedJournal(page)
    await page.getByRole('button', { name: '더 보기' }).click()
    await page.getByRole('menuitem', { name: '대화 지우기' }).click()
    await expect(page.getByRole('alertdialog')).toContainText('이 대화를 지울까요?')
    await page.getByRole('button', { name: '지우기', exact: true }).click()
    await expect(page.getByRole('heading', { name: '일지', level: 1 })).toBeVisible()
    await page.goto(`/journal/${sessionId}`)
    await expect(page.getByRole('alert')).toBeVisible()
    await expect(page.getByRole('region', { name: '결론' })).toHaveCount(0)
  })

  test('끝낸 대화를 글로 이어서 하고, 이어 간 뒤 새로고침해도 대화가 복원된다', async ({ page }) => {
    const sessionId = await endedJournal(page)
    await page.getByRole('button', { name: '글로 이어서' }).click()
    const messages = page.getByRole('list', { name: '대화 내용' })
    await expect(messages).toBeVisible()
    // 이전 대화가 이어지고 같은 세션을 쓴다
    await expect(messages).toContainText('노트에 저장해뒀어요')
    expect(latestSession()).toMatchObject({ id: sessionId, status: 'active' })
    await send(page, '__say__:다시 이어서 말해요.')
    await expect(messages).toContainText('다시 이어서 말해요.')

    await page.reload()
    await expect(page.getByRole('list', { name: '대화 내용' })).toContainText('다시 이어서 말해요.')
    await expect(page.getByRole('button', { name: '글로 대화 시작' })).toHaveCount(0)

    // 다시 끝내면 정리된다
    await page.getByRole('button', { name: '대화종료' }).click()
    await page.getByRole('button', { name: '끝내고 정리하기' }).click()
    await expect(page.getByText('대화 끝남')).toBeVisible()
    expect(latestSession()).toMatchObject({ id: sessionId, status: 'ended' })
  })
})
