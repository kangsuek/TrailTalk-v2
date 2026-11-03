import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Profile } from '../api/profile.ts'
import SettingsScreen from './SettingsScreen.tsx'

function baseProfile(patch: Partial<Profile> = {}): Profile {
  return {
    nickname: '다니엘',
    interests: ['전시', '테크'],
    persona_id: 'jenny',
    voice: null,
    speaking_rate: null,
    ack_enabled: true,
    keep_audio: false,
    chat_model: null,
    default_chat_model: 'sonnet',
    client: {} as Profile['client'],
    ...patch,
  }
}

/** GET/PUT /api/profile을 흉내 낸다. rejectWith가 있으면 PUT을 그 오류(422)로 거절한다 */
function mockProfile(initial: Profile, rejectWith?: string) {
  let current = initial
  const puts: Record<string, unknown>[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>
        puts.push(body)
        if (rejectWith) {
          return new Response(
            JSON.stringify({ error: { code: 'validation_error', message: rejectWith } }),
            { status: 422 },
          )
        }
        current = { ...current, ...body } as Profile
      }
      return new Response(JSON.stringify(current), { status: 200 })
    }),
  )
  return puts
}

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  localStorage.clear()
  delete document.documentElement.dataset.theme
})

beforeEach(() => {
  localStorage.clear()
})

const model = (name: string) => screen.getByRole('radio', { name: new RegExp(`^${name}`) })

describe('SettingsScreen', () => {
  it('프로필을 불러와 호칭·관심사·대화 모델을 보인다', async () => {
    mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    expect(await screen.findByLabelText('호칭')).toHaveValue('다니엘')
    expect(screen.getByText('3 / 20')).toBeInTheDocument()
    expect(screen.getByRole('list', { name: '관심사 목록' })).toHaveTextContent('전시')
    expect(screen.getByText('2 / 10')).toBeInTheDocument()
    expect(model('sonnet')).toHaveAttribute('aria-checked', 'true')
    expect(model('sonnet')).toHaveTextContent('기본')
    expect(model('haiku')).toHaveAttribute('aria-checked', 'false')
  })

  it('보류한 항목(이메일·보이스·말 속도·맞장구·음성 원본)은 만들지 않는다', async () => {
    mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    await screen.findByLabelText('호칭')
    expect(screen.queryByText(/이메일|보이스|목소리|말 속도|맞장구|음성 원본/)).toBeNull()
  })

  it('호칭을 바꾸고 칸을 벗어나면 바로 저장하고 "저장됨"을 보인다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    const input = await screen.findByLabelText('호칭')
    await userEvent.clear(input)
    await userEvent.type(input, '  민지 ')
    await userEvent.tab()
    await waitFor(() => expect(puts).toEqual([{ nickname: '민지' }]))
    expect(await screen.findByText('저장됨')).toBeInTheDocument()
    expect(input).toHaveValue('민지')
  })

  it('호칭이 그대로면 저장하지 않고, 비우면 기본 호칭(null)으로 돌린다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    const input = await screen.findByLabelText('호칭')
    await userEvent.click(input)
    await userEvent.tab()
    expect(puts).toEqual([])
    await userEvent.clear(input)
    await userEvent.tab()
    await waitFor(() => expect(puts).toEqual([{ nickname: null }]))
  })

  it('호칭이 20자를 넘으면 저장하지 않고 이유를 보이며 값을 되돌린다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    const input = await screen.findByLabelText('호칭')
    await userEvent.clear(input)
    await userEvent.type(input, '가'.repeat(21))
    await userEvent.tab()
    expect(await screen.findByRole('alert')).toHaveTextContent('호칭은 20자까지예요.')
    expect(input).toHaveValue('다니엘')
    expect(puts).toEqual([])
  })

  it('서버가 호칭을 거절(422)하면 그 필드 옆에 이유를 보이고 값을 되돌린다', async () => {
    mockProfile(baseProfile(), '호칭이 올바르지 않아요.')
    render(<SettingsScreen connection="connected" />)
    const input = await screen.findByLabelText('호칭')
    await userEvent.clear(input)
    await userEvent.type(input, '민지')
    await userEvent.tab()
    expect(await screen.findByRole('alert')).toHaveTextContent('호칭이 올바르지 않아요.')
    expect(input).toHaveValue('다니엘')
    expect(await screen.findByText('저장 안 됨')).toBeInTheDocument()
  })

  it('관심사는 Enter로 더하고 ×로 지우며 그때마다 바로 저장한다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    const input = await screen.findByLabelText('관심사 추가')
    await userEvent.type(input, ' 등산 {Enter}')
    await waitFor(() => expect(puts).toEqual([{ interests: ['전시', '테크', '등산'] }]))
    await waitFor(() => expect(input).toHaveValue(''))
    await userEvent.click(await screen.findByRole('button', { name: '테크 지우기' }))
    await waitFor(() => expect(puts[1]).toEqual({ interests: ['전시', '등산'] }))
  })

  it('저장 중에 관심사를 연달아 지워도 앞의 변경이 되살아나지 않는다', async () => {
    const profile = baseProfile({ interests: ['전시', '테크', '등산'] })
    let current = profile
    const puts: Record<string, unknown>[] = []
    let releaseFirst: () => void = () => {}
    const firstHeld = new Promise<void>((resolve) => (releaseFirst = resolve))
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init?: RequestInit) => {
        if (init?.method === 'PUT') {
          const body = JSON.parse(String(init.body)) as Record<string, unknown>
          puts.push(body)
          if (puts.length === 1) await firstHeld // 첫 저장이 끝나기 전에 다음 클릭이 들어오게 붙잡는다
          current = { ...current, ...body } as Profile
        }
        return new Response(JSON.stringify(current), { status: 200 })
      }),
    )
    render(<SettingsScreen connection="connected" />)
    await userEvent.click(await screen.findByRole('button', { name: '전시 지우기' }))
    await userEvent.click(screen.getByRole('button', { name: '테크 지우기' }))
    releaseFirst()
    await waitFor(() => expect(puts).toHaveLength(2))
    expect(puts[0]).toEqual({ interests: ['테크', '등산'] })
    expect(puts[1]).toEqual({ interests: ['등산'] }) // 첫 저장 결과를 바탕으로 만든 목록
    await waitFor(() =>
      expect(screen.getByRole('list', { name: '관심사 목록' })).toHaveTextContent(/^등산$/),
    )
  })

  it('중복·빈 값·개수 초과 관심사는 서버에 보내지 않고 이유를 보인다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    const input = await screen.findByLabelText('관심사 추가')
    await userEvent.type(input, '전시{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('이미 있는 관심사예요.')
    await userEvent.clear(input)
    await userEvent.click(screen.getByRole('button', { name: '추가' }))
    expect(screen.getByRole('alert')).toHaveTextContent('관심사를 입력해 주세요.')
    expect(puts).toEqual([])
  })

  it('서버가 관심사를 거절하면 목록은 그대로이고 이유를 보인다', async () => {
    mockProfile(baseProfile(), '관심사가 올바르지 않아요.')
    render(<SettingsScreen connection="connected" />)
    await userEvent.type(await screen.findByLabelText('관심사 추가'), '등산{Enter}')
    expect(await screen.findByRole('alert')).toHaveTextContent('관심사가 올바르지 않아요.')
    const list = screen.getByRole('list', { name: '관심사 목록' })
    expect(within(list).queryByText('등산')).toBeNull()
  })

  it('대화 모델을 고르면 바로 저장하고, 서버 기본 모델을 고르면 null을 보낸다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    await screen.findByLabelText('호칭')
    await userEvent.click(model('opus'))
    await waitFor(() => expect(puts).toEqual([{ chat_model: 'opus' }]))
    await waitFor(() => expect(model('opus')).toHaveAttribute('aria-checked', 'true'))
    expect(model('sonnet')).toHaveAttribute('aria-checked', 'false')
    await userEvent.click(model('sonnet'))
    await waitFor(() => expect(puts[1]).toEqual({ chat_model: null }))
  })

  it('이미 고른 모델을 다시 누르면 저장하지 않는다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    await screen.findByLabelText('호칭')
    await userEvent.click(model('sonnet'))
    expect(puts).toEqual([])
  })

  it('화면 모드는 이 기기에만 저장하고 바로 적용하며 서버에는 보내지 않는다', async () => {
    const puts = mockProfile(baseProfile())
    render(<SettingsScreen connection="connected" />)
    await screen.findByLabelText('호칭')
    await userEvent.click(screen.getByRole('radio', { name: /다크/ }))
    expect(document.documentElement.dataset.theme).toBe('dark')
    expect(localStorage.getItem('trailtalk.theme')).toBe('dark')
    await userEvent.click(screen.getByRole('radio', { name: /시스템 설정 따르기/ }))
    expect(document.documentElement.dataset.theme).toBeUndefined()
    expect(puts).toEqual([])
  })

  it('앱 정보에 서버 연결 상태와 캐릭터를 보인다', async () => {
    mockProfile(baseProfile())
    render(<SettingsScreen connection="offline" />)
    await screen.findByLabelText('호칭')
    expect(screen.getByText('연결 안 됨')).toBeInTheDocument()
    expect(screen.getByText(/jenny/)).toBeInTheDocument()
  })

  it('불러오기가 실패하면 이유와 다시 불러오기 버튼을 보인다', async () => {
    let fail = true
    vi.stubGlobal(
      'fetch',
      vi.fn(async () =>
        fail
          ? new Response('{}', { status: 500 })
          : new Response(JSON.stringify(baseProfile()), { status: 200 }),
      ),
    )
    render(<SettingsScreen connection="connected" />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: '다시 불러오기' }))
    expect(await screen.findByLabelText('호칭')).toHaveValue('다니엘')
  })
})
