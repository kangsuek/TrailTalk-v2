import { useEffect, useState, type ReactNode } from 'react'
import { fetchHealth } from './api/health.ts'
import Header from './components/Header.tsx'
import ConversationScreen from './screens/ConversationScreen.tsx'
import JournalListScreen from './screens/JournalListScreen.tsx'
import { HEALTH_INTERVAL_MS, nextConnection, type Connection } from './core/connection.ts'
import { CHAT_ROUTE, TAB_ROUTE, tabOf, type Tab } from './core/route.ts'
import { useRoute } from './hooks/useRoute.ts'

const TABS: { tab: Tab; name: string }[] = [
  { tab: 'chat', name: '대화' },
  { tab: 'journal', name: '일지' },
  { tab: 'settings', name: '설정' },
]

// 시안의 하단 탭 아이콘(24px 선 그림)
const TAB_ICONS: Record<Tab, ReactNode> = {
  chat: <path d="M4 5h16v11H9l-5 4z" />,
  journal: <path d="M6 3h12v18H6zM9 8h6M9 12h6" />,
  settings: (
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
  const [route, navigate] = useRoute()
  const tab = tabOf(route)
  const connection = useConnection()
  const label = TABS.find((item) => item.tab === tab)?.name ?? ''
  // 이 화면(대화 화면)이 지금 들고 있는 진행 중 대화. 일지 목록이 "대화로 돌아가기"를 정한다
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null)

  return (
    <div className="app">
      {/* 대화 화면은 페르소나 이름·상태를 담은 자기 헤더를 그린다 */}
      {tab === 'settings' && (
        <Header initial={label.slice(0, 1)} name={label} heading connection={connection} />
      )}
      <main className="app-main">
        {/* 탭을 바꿔도 진행 중인 대화가 사라지지 않게 숨기기만 한다 */}
        <div className="screen" hidden={tab !== 'chat'}>
          <ConversationScreen connection={connection} onSessionChange={setActiveSessionId} />
        </div>
        {route.name === 'journal' && (
          <JournalListScreen
            activeSessionId={activeSessionId}
            onOpenChat={() => navigate(CHAT_ROUTE)}
            onOpen={(id) => navigate({ name: 'journalDetail', id })}
          />
        )}
        {route.name === 'journalDetail' && (
          <p className="placeholder">일지 상세 화면은 준비 중입니다.</p>
        )}
        {tab === 'settings' && <p className="placeholder">{label} 화면은 준비 중입니다.</p>}
      </main>
      <nav className="tabs" aria-label="메인 메뉴">
        {TABS.map((item) => (
          <button
            key={item.tab}
            className="tab"
            aria-current={item.tab === tab ? 'page' : undefined}
            onClick={() => navigate(TAB_ROUTE[item.tab])}
          >
            <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
              {TAB_ICONS[item.tab]}
            </svg>
            {item.name}
          </button>
        ))}
      </nav>
    </div>
  )
}
