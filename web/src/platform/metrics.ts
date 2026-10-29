// 공통 계측 훅의 브라우저 인스턴스(V2-M0-05): window.__tt_metrics로 노출한다. 정의는 삭제된 docs/V2/metrics-hook.md(git 이력).
import { createMetrics, type Metrics } from '../core/metrics'

declare global {
  interface Window {
    __tt_metrics?: Metrics
  }
}

export const metrics: Metrics = createMetrics(() => performance.now())

if (typeof window !== 'undefined') window.__tt_metrics = metrics
