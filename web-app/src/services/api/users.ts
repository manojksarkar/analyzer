import { http } from '../../lib/http'

export interface OrgUser {
  id: string
  name: string
  email: string
  initials: string
}

export const usersApi = {
  search: async (q: string): Promise<OrgUser[]> => {
    const r = await http.get<{ users: OrgUser[] }>('/users/search', { q })
    return r.users
  },
}
