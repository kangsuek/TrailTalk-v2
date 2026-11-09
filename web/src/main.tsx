import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { appUpdate } from './hooks/appUpdate.ts'
import { applyTheme, readTheme } from './hooks/theme.ts'

// 첫 그림부터 이 기기에서 고른 화면 모드로 그린다(설정 03)
applyTheme(readTheme())

// 운영 빌드에서만 서비스 워커를 등록한다(오프라인 앱 껍데기·새 버전 감지). 개발 서버는 캐시가 방해된다
if (import.meta.env.PROD) appUpdate.start()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
