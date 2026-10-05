import { http } from '../../lib/http'
import type { TeamMember, UserRole } from '../../types'
import { mapMember, type ApiMember } from '../mappers'

/** What adding someone did. An address with no account got one, with a temporary password the
 * API answers ONCE (REVIEW_APPROVE_API_SPEC: members). */
export interface InviteResult {
  email: string
  accountCreated: boolean
  temporaryPassword: string | null
}

interface ApiInviteResponse {
  invite?: { email?: string }
  account?: { created?: boolean; temporary_password?: string | null }
}

export const teamApi = {
  list: async (projectId: string): Promise<TeamMember[]> => {
    const r = await http.get<{ members: ApiMember[] }>(`/projects/${projectId}/members`)
    return r.members.map(mapMember)
  },
  listPending: async (projectId: string): Promise<TeamMember[]> => {
    const r = await http.get<{ pending: ApiMember[] }>(`/projects/${projectId}/members/pending`)
    return r.pending.map(mapMember)
  },
  invite: (projectId: string, email: string, role: UserRole): Promise<InviteResult> =>
    http
      .post<ApiInviteResponse>(`/projects/${projectId}/members/invite`, { email, role })
      .then((r) => ({
        email: r?.invite?.email ?? email,
        accountCreated: Boolean(r?.account?.created),
        temporaryPassword: r?.account?.temporary_password ?? null,
      })),
  updateRole: (projectId: string, userId: string, role: UserRole): Promise<TeamMember> =>
    http
      .patch<{ member: ApiMember }>(`/projects/${projectId}/members/${userId}/role`, { role })
      .then((r) => mapMember(r.member)),
  remove: (projectId: string, userId: string): Promise<void> =>
    http.del(`/projects/${projectId}/members/${userId}`),
  cancelInvite: (projectId: string, inviteId: string): Promise<void> =>
    http.del(`/projects/${projectId}/members/pending/${inviteId}`),
}
