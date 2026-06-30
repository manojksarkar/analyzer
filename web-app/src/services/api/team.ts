import { http } from '../../lib/http'
import type { TeamMember, UserRole } from '../../types'
import { mapMember, type ApiMember } from '../mappers'

export const teamApi = {
  list: async (projectId: string): Promise<TeamMember[]> => {
    const r = await http.get<{ members: ApiMember[] }>(`/projects/${projectId}/members`)
    return r.members.map(mapMember)
  },
  listPending: async (projectId: string): Promise<TeamMember[]> => {
    const r = await http.get<{ pending: ApiMember[] }>(`/projects/${projectId}/members/pending`)
    return r.pending.map(mapMember)
  },
  invite: (projectId: string, email: string, role: UserRole): Promise<unknown> =>
    http.post(`/projects/${projectId}/members/invite`, { email, role }),
  updateRole: (projectId: string, userId: string, role: UserRole): Promise<TeamMember> =>
    http
      .patch<{ member: ApiMember }>(`/projects/${projectId}/members/${userId}/role`, { role })
      .then((r) => mapMember(r.member)),
  remove: (projectId: string, userId: string): Promise<void> =>
    http.del(`/projects/${projectId}/members/${userId}`),
  cancelInvite: (projectId: string, inviteId: string): Promise<void> =>
    http.del(`/projects/${projectId}/members/pending/${inviteId}`),
}
