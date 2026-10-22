import { useEffect, useState } from 'react'
import { fetchHealth } from './api/health.ts'
import {
  CONNECTION_LABEL,
  HEALTH_INTERVAL_MS,
  nextConnection,
  type Connection,
} from './core/connection.ts'

const TABS = ['대화', '일지', '설정'] as const
type Tab = (typeof TABS)[number]

function useConnection(): Connection {
  const [connection, setConnection] = useState<Connection>('checking')
  useEffect(() => {
    const controller = new AbortController()
    let inFlight = false // 이전 확인이 끝나기 전에는 새로 보내지 않는다
    const check = () => {
      if (inFlight) return
      inFlight = true
      void fetchHealth(controller.signal)
        .then((result) => {
          if (!controller.signal.aborted) setConnection(nextConnection(result))
        })
        .finally(() => {
          inFlight = false
        })
    }
    check()
    const timer = window.setInterval(check, HEALTH_INTERVAL_MS)
    return () => {
      controller.abort()
      window.clearInterval(timer)
    }
  }, [])
  return connection
}

export default function App() {
  const [tab, setTab] = useState<Tab>('대화')
  const connection = useConnection()
  const label = CONNECTION_LABEL[connection]

  return (
    <div className="app">
      <header className="app-header">
        <h1 className="app-title">TrailTalk</h1>
        <span className="conn" data-state={connection} role="status">
          <span aria-hidden="true">{label.icon}</span>
          {label.text}
        </span>
      </header>
      <main className="app-main">
        <p>{tab} 화면은 준비 중입니다.</p>
      </main>
      <nav className="tabs" aria-label="메인 메뉴">
        {TABS.map((name) => (
          <button
            key={name}
            className="tab"
            aria-current={name === tab ? 'page' : undefined}
            onClick={() => setTab(name)}
          >
            {name}
          </button>
        ))}
      </nav>
    </div>
  )
}
