// 앱 새 버전 감지(M6, PWA). 서비스 워커(/sw.js)를 등록하고, 이미 앱을 쓰는 중에 새 워커가 설치되어
// 대기하면 "새 버전이 있어요"를 알린다. 새 버전은 자동으로 적용하지 않고 설정 화면의 "적용" 버튼이
// apply()를 부를 때만 바꾼다(Spec 8절). 서비스 워커를 쓸 수 없는 환경(개발 서버·오래된 브라우저)에서는
// 아무 일도 하지 않는다.
import { useSyncExternalStore } from 'react'

/** 시험에서 흉내 낼 수 있는 서비스 워커 컨테이너의 최소 모양 */
interface WorkerLike {
  state: string
  postMessage(message: unknown): void
  addEventListener(type: 'statechange', handler: () => void): void
}
interface RegistrationLike {
  waiting: WorkerLike | null
  installing: WorkerLike | null
  addEventListener(type: 'updatefound', handler: () => void): void
  update(): Promise<unknown>
}
interface ContainerLike {
  controller: unknown
  register(url: string): Promise<RegistrationLike>
  addEventListener(type: 'controllerchange', handler: () => void): void
}
interface VisibilityLike {
  addEventListener(type: 'visibilitychange', handler: () => void): void
}

export interface AppUpdate {
  /** 서비스 워커를 등록하고 새 버전을 지켜본다. 두 번 불러도 한 번만 등록한다 */
  start(): void
  subscribe(listener: () => void): () => void
  /** 새 버전을 적용할 수 있는가 */
  getSnapshot(): boolean
  /** 새 버전으로 바꾼다. 바뀌면 화면을 한 번 새로 고친다 */
  apply(): void
}

export function createAppUpdate(
  container: ContainerLike | undefined,
  reload: () => void,
  page: { visibility: VisibilityLike; isVisible: () => boolean } | undefined = undefined,
): AppUpdate {
  const listeners = new Set<() => void>()
  let ready = false
  let waiting: WorkerLike | null = null
  let applying = false
  let started = false

  const setReady = (worker: WorkerLike) => {
    waiting = worker
    ready = true
    for (const listener of listeners) listener()
  }

  const watch = (registration: RegistrationLike) => {
    // 이미 대기 중인 워커(앱을 닫았다 열기 전에 설치가 끝난 경우)
    if (registration.waiting && container?.controller) setReady(registration.waiting)
    registration.addEventListener('updatefound', () => {
      const worker = registration.installing
      worker?.addEventListener('statechange', () => {
        // 제어 중인 워커가 없으면 처음 설치라 안내하지 않는다
        if (worker.state === 'installed' && container?.controller) setReady(worker)
      })
    })
    // 탭을 다시 열었을 때 새 버전이 있는지 확인한다
    page?.visibility.addEventListener('visibilitychange', () => {
      if (page.isVisible()) void registration.update().catch(() => undefined)
    })
  }

  return {
    start() {
      if (!container || started) return
      started = true
      // 적용을 눌러 제어 워커가 바뀐 때만 새로 고친다(다른 탭이 적용한 경우에 이 탭을 흔들지 않는다)
      container.addEventListener('controllerchange', () => {
        if (applying) {
          applying = false
          reload()
        }
      })
      container
        .register('/sw.js')
        .then(watch)
        .catch(() => undefined) // 등록에 실패해도 앱은 그대로 동작한다
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    getSnapshot: () => ready,
    apply() {
      if (!waiting) return
      applying = true
      waiting.postMessage({ type: 'SKIP_WAITING' })
    },
  }
}

/** 앱 하나가 쓰는 감지기. 개발 서버에서는 서비스 워커를 등록하지 않는다(main.tsx) */
export const appUpdate: AppUpdate = createAppUpdate(
  typeof navigator !== 'undefined' && 'serviceWorker' in navigator
    ? (navigator.serviceWorker as unknown as ContainerLike)
    : undefined,
  () => location.reload(),
  typeof document !== 'undefined'
    ? { visibility: document, isVisible: () => document.visibilityState === 'visible' }
    : undefined,
)

/** 새 버전을 적용할 수 있는지와 적용 함수 */
export function useAppUpdate(): { updateReady: boolean; applyUpdate: () => void } {
  const updateReady = useSyncExternalStore(appUpdate.subscribe, appUpdate.getSnapshot)
  return { updateReady, applyUpdate: appUpdate.apply }
}
