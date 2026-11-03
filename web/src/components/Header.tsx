import { CONNECTION_LABEL, type Connection } from '../core/connection.ts'
import UsageMeter from './UsageMeter.tsx'

interface Props {
  /** 아바타에 넣을 글자 */
  initial: string
  name: string
  /** 이름 아래 한 줄(상태). 없으면 이름만 보인다 */
  sub?: string
  /** 이름을 제목(h1)으로 쓸지. 화면에 제목이 하나만 있어야 한다 */
  heading?: boolean
  connection: Connection
  /** 상태 줄의 색(음성 대화: 듣기·처리 중·말하기). 없으면 기본 색 */
  tone?: string
}

// 시안의 헤더: 왼쪽에 아바타·이름·상태, 오른쪽에 남은 토큰 막대.
// 서버 연결 상태는 막대 옆에 아이콘으로 두고 문구는 화면 낭독용으로만 둔다(좁은 폭, 시안과 다름).
export default function Header({ initial, name, sub, heading, connection, tone }: Props) {
  const label = CONNECTION_LABEL[connection]
  return (
    <header className="app-header">
      <div className="app-who">
        <div className="avatar" aria-hidden="true">
          {initial}
        </div>
        <div>
          {heading ? (
            <h1 className="app-title chat-name">{name}</h1>
          ) : (
            <div className="app-title chat-name">{name}</div>
          )}
          {sub && (
            <div className="chat-status" data-tone={tone}>
              {sub}
            </div>
          )}
        </div>
      </div>
      <div className="app-right">
        <UsageMeter />
        <span className="conn" data-state={connection} role="status" title={label.text}>
          <span aria-hidden="true">{label.icon}</span>
          <span className="sr-only">{label.text}</span>
        </span>
      </div>
    </header>
  )
}
