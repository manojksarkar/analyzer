import type { TeamMember, UserRole } from '../../types'
import { relativeTime, avatarPalette } from '../../lib/format'

export interface ApiMember {
  id: string; user_id: string; name: string; email: string; initials: string
  role: string; status: string; joined_at: string | null
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
    role: m.role as UserRole,
    lastActive: pending ? 'Invited' : relativeTime(m.joined_at),
    avatarColor: pal.bg,
    avatarTextColor: pal.text,
    pending,
  }
}
