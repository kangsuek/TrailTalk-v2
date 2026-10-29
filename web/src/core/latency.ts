// 음성 턴 지연 보고(Spec 5.1, 규약 2.15, 계획 M3-12). 말이 끝난 때 → 요청을 시작한 때 → 첫 답변 소리가 재생되기
// 시작한 때를 한 턴에 한 번만 재서 보고할 값을 만든다. 시계(now)는 호출한 쪽이 준다(단조 시계 ms).
//
// 보고하지 않는 경우: 끊은 턴(cancel), 소리 없이 끝난 턴, 인사말·마무리 멘트의 소리(호출하지 않는다).

export interface LatencyReport {
  turnId: string
  speechToRequestMs: number // 말이 실제로 끝난 때(VAD 종료 감지 − 무음 대기) → 요청 시작
  requestToPlaybackMs: number // 요청 시작 → 첫 답변 소리 재생 시작(맞장구 제외)
  firstSoundNotice: boolean // 첫 소리가 검색 안내 음성이었다
}

export interface LatencyTracker {
  /** 음성 턴 요청을 시작했다. speechEndedAt: 말소리가 실제로 끝난 시각(없으면 요청 시각으로 본다) */
  begin(speechEndedAt: number | null): void
  /** 서버가 이 턴의 ID를 알렸다(`turn` 이벤트) */
  attach(turnId: string): void
  /** 첫 답변 소리가 재생되기 시작했다. 보고할 값을 한 번만 돌려주고 그 뒤에는 null이다 */
  playbackStarted(notice: boolean): LatencyReport | null
  /** 이 턴은 보고하지 않는다(끊음·오류·종료) */
  cancel(): void
}

export function createLatencyTracker(now: () => number): LatencyTracker {
  let current: { speechEndedAt: number; requestAt: number; turnId: string | null } | null = null
  return {
    begin(speechEndedAt) {
      const requestAt = now()
      current = { speechEndedAt: speechEndedAt ?? requestAt, requestAt, turnId: null }
    },
    attach(turnId) {
      if (current !== null) current.turnId = turnId
    },
    playbackStarted(notice) {
      // turn 이벤트 전에 소리가 나면(맞장구 등) 아직 보고할 턴 ID가 없다: 기다린다
      if (current === null || current.turnId === null) return null
      const { turnId, speechEndedAt, requestAt } = current
      current = null // 턴마다 한 번
      return {
        turnId,
        speechToRequestMs: Math.max(0, Math.round(requestAt - speechEndedAt)),
        requestToPlaybackMs: Math.max(0, Math.round(now() - requestAt)),
        firstSoundNotice: notice,
      }
    },
    cancel() {
      current = null
    },
  }
}
