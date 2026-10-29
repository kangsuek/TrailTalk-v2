// 대화 중 기기 연동(규약 6.6, 계획 M3-11): 화면이 꺼지지 않게 Screen Wake Lock을 쥐고,
// 이어폰 버튼(Media Session의 재생/일시정지)을 큰 버튼 `tap`으로 받는다. 지원하지 않는 브라우저에서는
// 아무 일도 하지 않는다(대화는 계속된다).

interface WakeLockSentinelLike {
  release(): Promise<void>
  addEventListener?(type: 'release', listener: () => void): void // 브라우저가 풀면(탭이 가려질 때 등) 온다
}

interface NavigatorLike {
  wakeLock?: { request(type: 'screen'): Promise<WakeLockSentinelLike> }
  mediaSession?: {
    metadata: unknown
    playbackState: string
    setActionHandler(action: string, handler: (() => void) | null): void
  }
}

export interface WakeLock {
  acquire(): Promise<void>
  release(): Promise<void>
}

/**
 * 화면 켜 두기. 브라우저는 탭이 가려지면 잠금을 풀어 버리므로 다시 보일 때 되잡는다.
 * acquire는 여러 번 불러도 하나만 쥐고, release 뒤에는 되잡지 않는다.
 */
export function createWakeLock(
  nav: NavigatorLike = navigator as NavigatorLike,
  doc: Pick<Document, 'addEventListener' | 'removeEventListener' | 'visibilityState'> = document,
): WakeLock {
  let sentinel: WakeLockSentinelLike | null = null
  let wanted = false

  const request = async () => {
    if (!nav.wakeLock || sentinel) return
    try {
      const acquired = await nav.wakeLock.request('screen')
      sentinel = acquired
      // 브라우저가 스스로 풀면 잊어서 다시 보일 때 되잡을 수 있게 한다
      acquired.addEventListener?.('release', () => {
        if (sentinel === acquired) sentinel = null
      })
      if (!wanted) await release() // 기다리는 사이 release가 불렸다
    } catch {
      sentinel = null // 배터리 절약 모드 등으로 거절돼도 대화는 계속된다
    }
  }
  const onVisible = () => {
    if (wanted && doc.visibilityState === 'visible') void request()
  }
  const release = async () => {
    const current = sentinel
    sentinel = null
    try {
      await current?.release()
    } catch {
      // 이미 풀렸다
    }
  }

  return {
    async acquire() {
      if (wanted) return
      wanted = true
      doc.addEventListener('visibilitychange', onVisible)
      await request()
    },
    async release() {
      wanted = false
      doc.removeEventListener('visibilitychange', onVisible)
      await release()
    },
  }
}

/**
 * 이어폰 버튼(재생/일시정지)을 onTap으로 받는다. 돌려준 함수가 핸들러를 거둔다.
 * 재생 상태를 playing으로 알려 둬야 브라우저가 이 페이지로 미디어 키 이벤트를 보낸다.
 */
export function bindMediaSession(
  onTap: () => void,
  title: string,
  nav: NavigatorLike = navigator as NavigatorLike,
): () => void {
  const session = nav.mediaSession
  if (!session) return () => {}
  const actions = ['play', 'pause', 'stop']
  try {
    if (typeof MediaMetadata !== 'undefined') session.metadata = new MediaMetadata({ title })
    session.playbackState = 'playing'
    for (const action of actions) session.setActionHandler(action, onTap)
  } catch {
    // 일부 브라우저는 일부 동작을 지원하지 않는다
  }
  return () => {
    for (const action of actions) {
      try {
        session.setActionHandler(action, null)
      } catch {
        // 이미 거둔 동작이다
      }
    }
    try {
      session.playbackState = 'none'
    } catch {
      // 무시
    }
  }
}
