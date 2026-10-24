import { useEffect, useState, type ReactNode } from 'react'
import { fetchHealth } from './api/health.ts'
import Header from './components/Header.tsx'
import ConversationScreen from './screens/ConversationScreen.tsx'
import { HEALTH_INTERVAL_MS, nextConnection, type Connection } from './core/connection.ts'

const TABS = ['대화', '일지', '설정'] as const
type Tab = (typeof TABS)[number]

// 시안의 하단 탭 아이콘(24px 선 그림)
const TAB_ICONS: Record<Tab, ReactNode> = {
  대화: <path d="M4 5h16v11H9l-5 4z" />,
  일지: <path d="M6 3h12v18H6zM9 8h6M9 12h6" />,
  설정: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" />
    </>
  ),
}

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

  return (
    <div className="app">
      {/* 대화 화면은 페르소나 이름·상태를 담은 자기 헤더를 그린다 */}
      {tab !== '대화' && (
        <Header initial={tab.slice(0, 1)} name={tab} heading connection={connection} />
      )}
      <main className="app-main">
        {/* 탭을 바꿔도 진행 중인 대화가 사라지지 않게 숨기기만 한다 */}
        <div className="screen" hidden={tab !== '대화'}>
          <ConversationScreen connection={connection} />
        </div>
        {tab !== '대화' && <p className="placeholder">{tab} 화면은 준비 중입니다.</p>}
      </main>
      <nav className="tabs" aria-label="메인 메뉴">
        {TABS.map((name) => (
          <button
            key={name}
            className="tab"
            aria-current={name === tab ? 'page' : undefined}
            onClick={() => setTab(name)}
          >
            <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
              {TAB_ICONS[name]}
            </svg>
            {name}
          </button>
        ))}
      </nav>
    </div>
  )
}
