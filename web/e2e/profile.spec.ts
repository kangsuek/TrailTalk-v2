import { expect, test } from '@playwright/test'

// 웹 개발 서버의 /api 프록시를 거쳐 격리 서버(임시 DB)의 프로필 API를 실제로 부른다.
test.describe.configure({ mode: 'serial' })

test.describe('프로필 API', () => {
  test('처음 조회하면 기본값으로 만든다', async ({ request }) => {
    const response = await request.get('/api/profile')
    expect(response.status()).toBe(200)
    const body = await response.json()
    expect(body).toMatchObject({
      nickname: null,
      interests: [],
      persona_id: 'jenny',
      ack_enabled: true,
      keep_audio: false,
      chat_model: null,
      default_chat_model: 'sonnet',
      mail_ready: false,
    })
    expect(body.client.session.idle_timeout_minutes).toBe(30)
  })

  test('보낸 필드만 바꾸고 다음 조회에도 남는다', async ({ request }) => {
    const put = await request.put('/api/profile', {
      data: { nickname: '  지은  ', interests: ['등산', '사진', '등산'], chat_model: 'haiku' },
    })
    expect(put.status()).toBe(200)
    const body = await (await request.get('/api/profile')).json()
    expect(body).toMatchObject({
      nickname: '지은',
      interests: ['등산', '사진'],
      chat_model: 'haiku',
      ack_enabled: true,
    })
  })

  test('틀린 값은 422 오류 형식이고 아무것도 바꾸지 않는다', async ({ request }) => {
    const bad = await request.put('/api/profile', {
      data: { nickname: '새이름', speaking_rate: 9 },
    })
    expect(bad.status()).toBe(422)
    expect((await bad.json()).error.code).toBe('validation_error')
    const readOnly = await request.put('/api/profile', { data: { client: {} } })
    expect(readOnly.status()).toBe(422)
    const missing = await request.put('/api/profile', { data: { persona_id: 'nobody' } })
    expect(missing.status()).toBe(404)
    expect((await missing.json()).error.code).toBe('persona_not_found')
    expect((await (await request.get('/api/profile')).json()).nickname).toBe('지은')
  })

  test('null을 보내면 값을 지우고 기본으로 돌아간다', async ({ request }) => {
    const body = await (
      await request.put('/api/profile', { data: { nickname: null, chat_model: null } })
    ).json()
    expect(body.nickname).toBeNull()
    expect(body.chat_model).toBeNull()
  })
})
