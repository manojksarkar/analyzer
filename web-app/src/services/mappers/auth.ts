import type { AuthUser, AuthSession } from '../../types'

export interface ApiUser {
  id: string; name: string; email: string; initials: string
  avatar_url: string | null; created_at: string; role_in_project?: string
}
export interface ApiSignIn { access_token: string; refresh_token: string; user: ApiUser }

export const mapUser = (u: ApiUser): AuthUser => ({
  id: u.id, name: u.name, email: u.email, initials: u.initials,
})

export const mapSignIn = (r: ApiSignIn): AuthSession => ({
  user: mapUser(r.user),
  accessToken: r.access_token,
  refreshToken: r.refresh_token,
})
