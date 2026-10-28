import { useCallback, useEffect, useState } from 'react'
import { parseRoute, pathOf, type Route } from '../core/route.ts'

export type Navigate = (route: Route, options?: { replace?: boolean }) => void

/**
 * 주소창 경로와 화면을 맞춘다(History API, 의존성 없음). 뒤로 가기·앞으로 가기·새로고침이 같은 화면을
 * 연다. 모르는 경로나 끝 슬래시 같은 변형은 정규 경로로 바꿔 둔다.
 */
export function useRoute(): [Route, Navigate] {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.pathname))

  useEffect(() => {
    const onPop = () => setRoute(parseRoute(window.location.pathname))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  useEffect(() => {
    const canonical = pathOf(route)
    if (window.location.pathname !== canonical) window.history.replaceState(null, '', canonical)
  }, [route])

  const navigate = useCallback<Navigate>((next, options) => {
    const path = pathOf(next)
    if (window.location.pathname !== path) {
      if (options?.replace) window.history.replaceState(null, '', path)
      else window.history.pushState(null, '', path)
    }
    setRoute(next)
  }, [])

  return [route, navigate]
}
