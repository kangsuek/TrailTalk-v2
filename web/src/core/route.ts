// 화면 경로(History API, docs/client-contract.md 1.1). 경로 문자열과 화면 이름 사이의 변환만 하고
// 브라우저 API에는 기대지 않는다(src/core 규칙).

export type Route =
  | { name: 'chat' }
  | { name: 'journal' }
  | { name: 'journalDetail'; id: string }
  | { name: 'settings' }

/** 하단 탭. 일지 상세도 일지 탭에 속한다. */
export type Tab = 'chat' | 'journal' | 'settings'

export const CHAT_ROUTE: Route = { name: 'chat' }

/** 경로를 화면으로 바꾼다. 모르는 경로는 대화(시작 화면)다. */
export function parseRoute(pathname: string): Route {
  const parts = pathname.split('/').filter(Boolean)
  if (parts.length === 1 && parts[0] === 'journal') return { name: 'journal' }
  if (parts.length === 2 && parts[0] === 'journal') {
    const id = decode(parts[1])
    if (id) return { name: 'journalDetail', id }
  }
  if (parts.length === 1 && parts[0] === 'settings') return { name: 'settings' }
  return CHAT_ROUTE
}

/** 화면의 정규 경로. parseRoute와 서로 되돌릴 수 있다. */
export function pathOf(route: Route): string {
  switch (route.name) {
    case 'journal':
      return '/journal'
    case 'journalDetail':
      return `/journal/${encodeURIComponent(route.id)}`
    case 'settings':
      return '/settings'
    default:
      return '/'
  }
}

export function tabOf(route: Route): Tab {
  switch (route.name) {
    case 'journal':
    case 'journalDetail':
      return 'journal'
    case 'settings':
      return 'settings'
    default:
      return 'chat'
  }
}

export const TAB_ROUTE: Record<Tab, Route> = {
  chat: CHAT_ROUTE,
  journal: { name: 'journal' },
  settings: { name: 'settings' },
}

function decode(segment: string): string {
  try {
    return decodeURIComponent(segment)
  } catch {
    return '' // 깨진 퍼센트 인코딩은 없는 경로로 본다
  }
}
