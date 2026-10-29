import { describe, expect, it, vi } from 'vitest'
import { bindMediaSession, createWakeLock } from './deviceSession'

function fakeDoc() {
  const listeners = new Set<() => void>()
  return {
    visibilityState: 'visible' as DocumentVisibilityState,
    addEventListener: (_: string, fn: () => void) => listeners.add(fn),
    removeEventListener: (_: string, fn: () => void) => listeners.delete(fn),
    fire: () => listeners.forEach((fn) => fn()),
    count: () => listeners.size,
  }
}

function fakeNav() {
  const released: number[] = []
  const browserRelease: (() => void)[] = [] // 브라우저가 잠금을 푸는 것을 흉내 낸다
  let n = 0
  return {
    released,
    browserRelease,
    requests: () => n,
    nav: {
      wakeLock: {
        request: vi.fn(async () => {
          const id = ++n
          const listeners: (() => void)[] = []
          browserRelease.push(() => listeners.forEach((fn) => fn()))
          return {
            release: async () => void released.push(id),
            addEventListener: (_: 'release', fn: () => void) => void listeners.push(fn),
          }
        }),
      },
    },
  }
}

describe('Screen Wake Lock', () => {
  it('acquire는 잠금을 하나만 쥐고 release가 푼다', async () => {
    const { nav, released, requests } = fakeNav()
    const doc = fakeDoc()
    const lock = createWakeLock(nav, doc as never)
    await lock.acquire()
    await lock.acquire()
    expect(requests()).toBe(1)
    await lock.release()
    expect(released).toEqual([1])
    expect(doc.count()).toBe(0) // 리스너도 거둔다
  })

  it('탭이 가려져 브라우저가 잠금을 풀었다가 다시 보이면 되잡는다', async () => {
    const { nav, requests, browserRelease } = fakeNav()
    const doc = fakeDoc()
    const lock = createWakeLock(nav, doc as never)
    await lock.acquire()
    expect(requests()).toBe(1)
    doc.fire() // 아직 쥐고 있으면 되잡지 않는다
    await Promise.resolve()
    expect(requests()).toBe(1)
    browserRelease[0]() // 탭이 가려져 브라우저가 풀었다
    doc.visibilityState = 'hidden'
    doc.fire()
    await Promise.resolve()
    expect(requests()).toBe(1) // 가려진 동안에는 잡지 않는다
    doc.visibilityState = 'visible'
    doc.fire()
    await Promise.resolve()
    expect(requests()).toBe(2)
  })

  it('release 뒤에는 보이게 돼도 되잡지 않는다', async () => {
    const { nav, requests } = fakeNav()
    const doc = fakeDoc()
    const lock = createWakeLock(nav, doc as never)
    await lock.acquire()
    await lock.release()
    doc.fire()
    await Promise.resolve()
    expect(requests()).toBe(1)
    await lock.acquire()
    expect(requests()).toBe(2)
  })

  it('지원하지 않거나 거절돼도 예외 없이 지나간다', async () => {
    const doc = fakeDoc()
    await expect(createWakeLock({}, doc as never).acquire()).resolves.toBeUndefined()
    const denied = { wakeLock: { request: vi.fn(async () => Promise.reject(new Error('denied'))) } }
    const lock = createWakeLock(denied, doc as never)
    await expect(lock.acquire()).resolves.toBeUndefined()
    await expect(lock.release()).resolves.toBeUndefined()
  })
})

describe('Media Session(이어폰 버튼)', () => {
  function fakeSession() {
    const handlers = new Map<string, (() => void) | null>()
    return {
      handlers,
      nav: {
        mediaSession: {
          metadata: null as unknown,
          playbackState: 'none',
          setActionHandler: (action: string, fn: (() => void) | null) => void handlers.set(action, fn),
        },
      },
    }
  }

  it('재생·일시정지·정지 버튼이 모두 같은 tap 동작을 부르고, 해제하면 거둔다', () => {
    const { nav, handlers } = fakeSession()
    const onTap = vi.fn()
    const unbind = bindMediaSession(onTap, 'TrailTalk', nav)
    expect(nav.mediaSession.playbackState).toBe('playing')
    for (const action of ['play', 'pause', 'stop']) handlers.get(action)?.()
    expect(onTap).toHaveBeenCalledTimes(3)
    unbind()
    expect([...handlers.values()]).toEqual([null, null, null])
    expect(nav.mediaSession.playbackState).toBe('none')
  })

  it('Media Session이 없으면 아무 일도 하지 않는다', () => {
    const unbind = bindMediaSession(() => {}, 'TrailTalk', {})
    expect(() => unbind()).not.toThrow()
  })
})
