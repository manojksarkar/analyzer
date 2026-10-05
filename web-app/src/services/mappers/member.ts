import { z } from 'zod'
import type { TeamMember, UserRole } from '../../types'
import { relativeTime, avatarPalette } from '../../lib/format'

export const ApiMemberSchema = z.object({
  id: z.string(), user_id: z.string(), name: z.string(), email: z.string(), initials: z.string(),
  role: z.string(), status: z.string(), joined_at: z.string().nullable(),
})
export type ApiMember = z.infer<typeof ApiMemberSchema>

/** The web app's two roles. The server still accepts a third, `reviewer` (`analyzer.py grant
 *  --role reviewer`), which can do what a developer can: it is one here -- passed through as is,
 *  it was neither, and a reviewer lost Claim and the "My reviews" filter. */
export function toUserRole(raw: string | null | undefined): UserRole {
  return raw === 'admin' ? 'admin' : 'developer'
}

export function mapMember(m: ApiMember): TeamMember {
  const pal = avatarPalette(m.user_id || m.id)
  const pending = m.status === 'pending'
  return {
    id: m.id,
    userId: m.user_id,
    name: m.name,
    initials: m.initials,
    email: m.email,
    role: toUserRole(m.role),
    lastActive: pending ? 'Invited' : relativeTime(m.joined_at),
    avatarColor: pal.bg,
    avatarTextColor: pal.text,
    pending,
  }
}
