import Markdown from './Markdown.tsx'
import { groupTurns, type Turn } from '../core/journal.ts'

/** 일지 상세의 전문(시안 일지 05): 화자 이름, 내 말풍선·답변 말풍선, 병합된 뒷말은 한 말풍선 안에 점선으로 이음. */
export default function Transcript({ turns, personaName }: { turns: Turn[]; personaName: string }) {
  const bubbles = groupTurns(turns)
  if (bubbles.length === 0) return <p className="t-empty">남은 대화가 없어요.</p>
  return (
    <ol className="transcript" aria-label="전문">
      {bubbles.map((bubble) => {
        const mine = bubble.role === 'user'
        return (
          <li key={bubble.id} className="t-item" data-role={bubble.role}>
            <span className="t-who">{mine ? '나' : personaName}</span>
            <div className={mine ? 't-bubble t-user' : 't-bubble t-bot'} data-interrupted={bubble.interrupted}>
              {bubble.texts.map((text, index) => (
                <div key={index} className="t-part">
                  {mine ? text : <Markdown text={text} />}
                </div>
              ))}
            </div>
            {bubble.interrupted && (
              <span className="t-cut">
                <svg className="ic ic-xs" viewBox="0 0 24 24" aria-hidden="true">
                  <rect x="6" y="6" width="12" height="12" rx="2" />
                </svg>
                끝까지 말하지 못했어요
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}
