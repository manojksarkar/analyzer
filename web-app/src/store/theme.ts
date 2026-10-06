import { create } from 'zustand'

export type Theme = 'light' | 'dark'

/** localStorage key. index.html reads it before React paints, so a reload never flashes the
 *  other theme; keep the two in step. */
export const THEME_KEY = 'theme'
/** No saved choice: dark. */
export const DEFAULT_THEME: Theme = 'dark'

/** The saved theme, or the default. Blocked storage (private mode, site data off) throws: the
 *  default then applies, and a toggle lasts for this page only. */
export function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    /* storage blocked: use the default */
  }
  return DEFAULT_THEME
}

/** The theme is one attribute on <html>: index.css redefines the colour tokens under
 *  `:root[data-theme="dark"]` (and sets `color-scheme`, for native controls and scrollbars). */
export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme)
}

interface ThemeState {
  theme: Theme
  setTheme: (theme: Theme) => void
  toggleTheme: () => void
}

export const useThemeStore = create<ThemeState>((set, get) => ({
  theme: readTheme(),
  setTheme: (theme) => {
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch {
      /* storage blocked: the theme still changes, for this page */
    }
    applyTheme(theme)
    set({ theme })
  },
  toggleTheme: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
}))
