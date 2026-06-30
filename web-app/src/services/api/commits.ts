import { http } from '../../lib/http'
import type { Commit } from '../../types'
import { mapCommit, type ApiCommit } from '../mappers'

export const commitsApi = {
  list: async (
    projectId: string,
    opts: { page?: number; perPage?: number } = {},
  ): Promise<Commit[]> => {
    const r = await http.get<{ commits: ApiCommit[] }>(`/projects/${projectId}/commits`, {
      page: opts.page,
      per_page: opts.perPage,
    })
    return r.commits.map(mapCommit)
  },
}
