import { describe, expect, it, vi } from 'vitest'
import { createAppUpdate } from './appUpdate.ts'

// 서비스 워커 컨테이너·등록·워커를 흉내 내는 최소 가짜. 이벤트는 직접 쏜다.
class Emitter {
  private handlers = new Map<string, Array<() => void>>()
  addEventListener(type: string, handler: () => void) {
    this.handlers.set(type, [...(this.handlers.get(type) ?? []), handler])
  }
  emit(type: string) {
    for (const handler of this.handlers.get(type) ?? []) handler()
  }
}

class FakeWorker extends Emitter {
  state = 'installing'
  postMessage = vi.fn()
}

class FakeRegistration extends Emitter {
  waiting: FakeWorker | null = null
  installing: FakeWorker | null = null
  update = vi.fn().mockResolvedValue(undefined)
}

class FakeContainer extends Emitter {
  controller: object | null
  registration = new FakeRegistration()
  register = vi.fn().mockResolvedValue(this.registration)
  constructor(controller: object | null) {
    super()
    this.controller = controller
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

describe('앱 새 버전 감지', () => {
  it('서비스 워커를 지원하지 않으면 아무 일도 하지 않는다', () => {
    const update = createAppUpdate(undefined, vi.fn())
    update.start()
    expect(update.getSnapshot()).toBe(false)
    update.apply() // 던지지 않는다
  })

  it('처음 설치(제어 중인 워커 없음)는 새 버전 안내를 띄우지 않는다', async () => {
    const container = new FakeContainer(null)
    const update = createAppUpdate(container as never, vi.fn())
    update.start()
    await flush()
    const worker = new FakeWorker()
    container.registration.installing = worker
    container.registration.emit('updatefound')
    worker.state = 'installed'
    worker.emit('statechange')
    expect(container.register).toHaveBeenCalledWith('/sw.js')
    expect(update.getSnapshot()).toBe(false)
  })

  it('이미 앱을 쓰는 중에 새 워커가 설치되면 안내를 띄운다', async () => {
    const container = new FakeContainer({})
    const update = createAppUpdate(container as never, vi.fn())
    const listener = vi.fn()
    update.subscribe(listener)
    update.start()
    await flush()
    const worker = new FakeWorker()
    container.registration.installing = worker
    container.registration.emit('updatefound')
    expect(update.getSnapshot()).toBe(false) // 설치가 끝나기 전에는 아직
    worker.state = 'installed'
    worker.emit('statechange')
    expect(update.getSnapshot()).toBe(true)
    expect(listener).toHaveBeenCalled()
  })

  it('열자마자 이미 대기 중인 워커가 있으면 바로 안내한다', async () => {
    const container = new FakeContainer({})
    container.registration.waiting = new FakeWorker()
    const update = createAppUpdate(container as never, vi.fn())
    update.start()
    await flush()
    expect(update.getSnapshot()).toBe(true)
  })

  it('적용하면 대기 워커에 SKIP_WAITING을 보내고, 제어 워커가 바뀌면 한 번만 새로 고친다', async () => {
    const container = new FakeContainer({})
    const waiting = new FakeWorker()
    container.registration.waiting = waiting
    const reload = vi.fn()
    const update = createAppUpdate(container as never, reload)
    update.start()
    await flush()
    update.apply()
    expect(waiting.postMessage).toHaveBeenCalledWith({ type: 'SKIP_WAITING' })
    expect(reload).not.toHaveBeenCalled() // 메시지를 보냈을 뿐, 바뀌기 전에는 새로 고치지 않는다
    container.emit('controllerchange')
    container.emit('controllerchange')
    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('적용을 누르지 않았는데 제어 워커가 바뀌어도 새로 고치지 않는다(다른 탭의 적용)', async () => {
    const container = new FakeContainer({})
    const reload = vi.fn()
    createAppUpdate(container as never, reload).start()
    await flush()
    container.emit('controllerchange')
    expect(reload).not.toHaveBeenCalled()
  })

  it('탭이 다시 보이면 새 버전을 확인한다', async () => {
    const container = new FakeContainer({})
    const visibility = new Emitter()
    const update = createAppUpdate(container as never, vi.fn(), {
      visibility: visibility as never,
      isVisible: () => true,
    })
    update.start()
    await flush()
    visibility.emit('visibilitychange')
    expect(container.registration.update).toHaveBeenCalledTimes(1)
  })

  it('등록에 실패해도 앱은 그대로 동작한다', async () => {
    const container = new FakeContainer({})
    container.register.mockRejectedValue(new Error('SecurityError'))
    const update = createAppUpdate(container as never, vi.fn())
    update.start()
    await flush()
    expect(update.getSnapshot()).toBe(false)
  })
})
