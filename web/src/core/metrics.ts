// 공통 계측 훅(V2-M0-05): VAD 프레임·확정·종료·재생 시작·소스 정지 시각을 메모리에 모은다.
// 브라우저에서는 platform/metrics.ts가 window.__tt_metrics로 노출한다(Playwright 평가가 읽는다).
// 정의: 삭제된 docs/V2/metrics-hook.md(git 이력). 시계는 지연 측정과 같은 단조 시계(performance.now) ms다.
export interface MetricFrame {
  t: number // VAD가 프레임 하나(약 32ms)를 처리한 시각
  p: number // 음성 확률(0~1)
}

export type MetricData = Record<string, number | string | boolean | null>

export interface MetricMark {
  t: number
  type: string
  data?: MetricData
}

export interface Metrics {
  /** 가장 최근 프레임부터 maxFrames개까지(오래된 것부터 버린다) */
  readonly frames: MetricFrame[]
  readonly marks: MetricMark[]
  frame(probability: number): void
  mark(type: string, data?: MetricData): void
  /** 두 배열을 비운다(같은 배열 객체를 유지해 이미 잡은 참조도 비워진다) */
  clear(): void
}

export const MAX_FRAMES = 3000 // 약 96초
export const MAX_MARKS = 1000

function trim<T>(items: T[], max: number) {
  if (items.length > max) items.splice(0, items.length - max)
}

export function createMetrics(now: () => number, maxFrames = MAX_FRAMES, maxMarks = MAX_MARKS): Metrics {
  const frames: MetricFrame[] = []
  const marks: MetricMark[] = []
  return {
    frames,
    marks,
    frame(probability) {
      frames.push({ t: now(), p: probability })
      trim(frames, maxFrames)
    },
    mark(type, data) {
      marks.push(data === undefined ? { t: now(), type } : { t: now(), type, data })
      trim(marks, maxMarks)
    },
    clear() {
      frames.length = 0
      marks.length = 0
    },
  }
}
