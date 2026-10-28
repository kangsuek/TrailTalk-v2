import { KIND_LABEL, countPills, type NoteCounts } from '../core/journal.ts'

/** 노트 종류별 개수 알약('아이디어 3'). all이면 0인 종류도 보인다(대화 끝난 뒤 저장한 것). */
export default function CountPills({ counts, all = false }: { counts: NoteCounts; all?: boolean }) {
  const pills = all
    ? (['idea', 'todo', 'memo'] as const).map((kind) => ({ kind, text: `${KIND_LABEL[kind]} ${counts[kind]}` }))
    : countPills(counts)
  if (pills.length === 0) return null
  return (
    <span className="j-pills">
      {pills.map((pill) => (
        <span key={pill.kind} className={`pill pill-${pill.kind}`}>
          {pill.text}
        </span>
      ))}
    </span>
  )
}
