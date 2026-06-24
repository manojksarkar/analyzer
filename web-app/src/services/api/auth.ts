import { http } from '../../lib/http'
import type { AuthSession, AuthUser } from '../../types'
import { mapSignIn, mapUser, type ApiSignIn, type ApiUser } from '../mappers'

export const authApi = {
  /** Email + password. The API matches on email only (see INTEGRATION_NOTES). */
  signIn: async (email: string, password: string): Promise<AuthSession> => {
    const r = await http.post<ApiSignIn>('/auth/signin', { email: email.trim(), password })
    return mapSignIn(r)
  },
  me: async (): Promise<AuthUser> => {
    const r = await http.get<{ user: ApiUser }>('/auth/me')
    return mapUser(r.user)
  },
  signOut: async (): Promise<void> => {
    try {
      await http.post('/auth/signout')
    } catch {
      /* stateless server-side — clearing local tokens is what matters */
    }
  },
}
