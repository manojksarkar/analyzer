import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'
import { applyTheme, useThemeStore } from './store/theme'

// index.html set it before the first paint; this keeps the attribute and the store in step.
applyTheme(useThemeStore.getState().theme)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
