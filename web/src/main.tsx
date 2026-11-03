import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyTheme, readTheme } from './hooks/theme.ts'

// 첫 그림부터 이 기기에서 고른 화면 모드로 그린다(설정 03)
applyTheme(readTheme())

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
