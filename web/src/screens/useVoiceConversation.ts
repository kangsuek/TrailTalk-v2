// 음성 대화 훅(계획 M3-13): 컨트롤러를 화면 수명에 맞춰 만들고 정리하며, 대화 중에는 화면이 꺼지지 않게 하고
// (Screen Wake Lock) 이어폰 버튼을 큰 버튼 한 번(tap)으로 받는다(Media Session).
import { useCallback, useEffect, useRef, useState } from 'react'
import { initialSession, type SessionState } from '../core/index.ts'
import type { ConversationAction } from '../core/conversation.ts'
import type { SessionReopened } from '../api/conversation.ts'
import { bindMediaSession, createWakeLock } from '../platform/deviceSession.ts'
import { preloadPlatform } from './lazyPlatform.ts'
import {
  createVoiceController,
  type VoiceClosed,
  type VoiceController,
  type VoiceDeps,
} from './voiceController.ts'

export function useVoiceConversation(
  dispatch: (action: ConversationAction) => void,
  onClosed: (sessionId: string, closed: VoiceClosed) => void,
  personaName: string | null,
  deps?: Partial<VoiceDeps>,
) {
  const [machine, setMachine] = useState<SessionState>(initialSession)
  const controller = useRef<VoiceController | null>(null)
  const [initialDeps] = useState(deps) // 처음 받은 의존성으로 고정한다(테스트용)
  const onClosedRef = useRef(onClosed)
  useEffect(() => {
    onClosedRef.current = onClosed
  })
  // 음성 모듈을 불러왔는지(null: 불러오는 중, false: 실패). 다 불러오기 전에는 "음성으로"를 막는다
  const [ready, setReady] = useState<boolean | null>(null)

  useEffect(() => {
    let alive = true
    void preloadPlatform().then((loaded) => alive && setReady(loaded))
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const current = createVoiceController({
      dispatch,
      onState: setMachine,
      onClosed: (id, closed) => onClosedRef.current(id, closed),
      deps: initialDeps,
    })
    controller.current = current
    return () => {
      controller.current = null
      setMachine(initialSession)
      void current.dispose()
    }
  }, [dispatch, initialDeps])

  const tap = useCallback(() => controller.current?.tap(), [])
  const requestEnd = useCallback(() => controller.current?.requestEnd(), [])
  const confirmEnd = useCallback(() => controller.current?.confirmEnd(), [])
  const cancelEnd = useCallback(() => controller.current?.cancelEnd(), [])
  const longPress = useCallback(() => controller.current?.longPress(), [])
  const resume = useCallback(
    (reopened: SessionReopened) => controller.current?.resume(reopened) ?? false,
    [],
  )
  const sendText = useCallback(
    (text: string, onUnsent?: (text: string) => void) =>
      controller.current?.sendText(text, onUnsent) ?? false,
    [],
  )

  // 대화 중(대기·정리 밖)에는 화면을 켜 두고 이어폰 버튼을 받는다
  const active = machine.name !== 'idle' && machine.name !== 'closing'
  useEffect(() => {
    if (!active) return
    const lock = createWakeLock()
    void lock.acquire()
    const unbind = bindMediaSession(tap, personaName ?? 'TrailTalk')
    return () => {
      unbind()
      void lock.release()
    }
  }, [active, tap, personaName])

  return { machine, tap, requestEnd, confirmEnd, cancelEnd, longPress, sendText, resume, ready }
}
