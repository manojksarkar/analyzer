import { create } from 'zustand'
import { persist, createJSONStorage, type StateStorage } from 'zustand/middleware'
import { authApi } from '../services/api'
import type { AuthUser } from '../types'

const REMEMBER_KEY = 'auth-remember'

/**
 * Where the session is stored: `localStorage` (survives browser restart) when
 * "Remember me" is on, otherwise `sessionStorage` (cleared when the tab/browser
 * closes). The preference flag itself lives in localStorage so it can be read
 * synchronously when the persist middleware rehydrates on load.
 */
function activeStorage(): Storage {
  return localStorage.getItem(REMEMBER_KEY) === '0' ? sessionStorage : localStorage
}

/** Record the remember-me choice and drop any stale session from the other store. */
function applyRememberPreference(remember: boolean): void {
  localStorage.setItem(REMEMBER_KEY, remember ? '1' : '0')
  ;(remember ? sessionStorage : localStorage).removeItem('auth')
}

const authStorage: StateStorage = {
  getItem: (name) => activeStorage().getItem(name),
  setItem: (name, value) => activeStorage().setItem(name, value),
  removeItem: (name) => activeStorage().removeItem(name),
}

interface AuthState {
  user: AuthUser | null
  accessToken: string | null
  refreshToken: string | null
  isAuthenticated: boolean
  /** False until the persisted session has been validated against the API on load. */
  bootstrapped: boolean
  signIn: (email: string, password: string, remember?: boolean) => Promise<void>
  /** Replace only the access token (used by the HTTP client after a refresh). */
  setAccessToken: (token: string) => void
  /** Validate the persisted token on app start and hydrate a fresh user. */
  bootstrap: () => Promise<void>
  signOut: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      user: null,
      accessToken: null,
      refreshToken: null,
      isAuthenticated: false,
      bootstrapped: false,

      signIn: async (email, password, remember = false) => {
        // Choose the storage target before the state write below persists tokens.
        applyRememberPreference(remember)
        const { user, accessToken, refreshToken } = await authApi.signIn(email, password)
        set({ isAuthenticated: true, user, accessToken, refreshToken })
      },

      setAccessToken: (token) => set({ accessToken: token }),

      bootstrap: async () => {
        // No persisted token → nothing to validate.
        if (!get().accessToken) {
          set({ bootstrapped: true })
          return
        }
        try {
          // Re-fetch the user; the HTTP client refreshes/clears tokens on 401.
          const user = await authApi.me()
          set({ user, isAuthenticated: true, bootstrapped: true })
        } catch {
          // Invalid/expired session — clear it; ProtectedRoute redirects to /signin.
          set({ user: null, accessToken: null, refreshToken: null, isAuthenticated: false })
          set({ bootstrapped: true })
        }
      },

      signOut: () => {
        // Clear both stores so no stale session lingers in either.
        localStorage.removeItem('auth')
        sessionStorage.removeItem('auth')
        set({ user: null, accessToken: null, refreshToken: null, isAuthenticated: false })
      },
    }),
    {
      name: 'auth',
      storage: createJSONStorage(() => authStorage),
      // `bootstrapped` is per-session and must never be restored from storage,
      // or a stale `true` would skip validation on the next load.
      partialize: (s) => ({
        user: s.user,
        accessToken: s.accessToken,
        refreshToken: s.refreshToken,
        isAuthenticated: s.isAuthenticated,
      }),
    }
  )
)
