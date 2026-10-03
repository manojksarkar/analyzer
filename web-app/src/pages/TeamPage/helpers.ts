import type { TeamMember } from '../../types'

/** Why the project's only active admin cannot be made a developer or removed (the API refuses it
 *  with 409 `LAST_ADMIN`: nobody could add members, assign or approve documents any more). */
export const LAST_ADMIN_REASON = "This is the project's only admin. Make someone else an admin first."

/** Is `m` the project's only active admin? A pending invite is not a member yet. */
export function isLastAdmin(m: TeamMember, members: TeamMember[]): boolean {
  if (m.pending || m.role !== 'admin') return false
  return !members.some((o) => o.id !== m.id && !o.pending && o.role === 'admin')
}

/** A change that is asked about before it is made: removing anyone, or demoting yourself. */
export interface MemberChange {
  action: 'remove' | 'demote'
  member: TeamMember
}

/** Does making `m` a `role` need a confirmation first? Only taking your own admin role away. */
export function asksBeforeRoleChange(m: TeamMember, role: TeamMember['role'], meId: string): boolean {
  return role === 'developer' && m.role === 'admin' && !!meId && m.userId === meId
}
