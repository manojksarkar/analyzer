import { z } from 'zod'
import type { AuthUser, AuthSession } from '../../types'

export const ApiUserSchema = z.object({
  id: z.string(), name: z.string(), email: z.string(), initials: z.string(),
  avatar_url: z.string().nullable(), created_at: z.string(), role_in_project: z.string().optional(),
})
export type ApiUser = z.infer<typeof ApiUserSchema>

export const ApiSignInSchema = z.object({
  access_token: z.string(), refresh_token: z.string(), user: ApiUserSchema,
})
export type ApiSignIn = z.infer<typeof ApiSignInSchema>

export const mapUser = (u: ApiUser): AuthUser => ({
  id: u.id, name: u.name, email: u.email, initials: u.initials,
})

export const mapSignIn = (r: ApiSignIn): AuthSession => ({
  user: mapUser(r.user),
  accessToken: r.access_token,
  refreshToken: r.refresh_token,
})
