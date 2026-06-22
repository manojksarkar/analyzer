import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { UserRole } from '../types'

interface AuthUser {
  id: string
  name: string
  email: string
  initials: string
  role: UserRole
}

interface AuthState {
  user: AuthUser | null
  isAuthenticated: boolean
  signIn: (email: string, _password: string) => Promise<void>
  signOut: () => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      isAuthenticated: false,

      signIn: async (email: string, _password: string) => {
        // Replace with real API call
        await new Promise((r) => setTimeout(r, 600))
        set({
          isAuthenticated: true,
          user: {
            id: 'u1',
            name: 'Manoj Sarkar',
            email,
            initials: 'MS',
            role: 'admin',
          },
        })
      },

      signOut: () => set({ user: null, isAuthenticated: false }),
    }),
    { name: 'auth' }
  )
)
