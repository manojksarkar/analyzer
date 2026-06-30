import { http } from '../../lib/http'
import type { Commit } from '../../types'
import { mapCommit, type ApiCommit } from '../mappers'

export interface CommitList {
  commits: Commit[]
  /** ISO time the commits were last synced from the repo, or null. */
  lastSyncedAt: string | null
}

export const commitsApi = {
  list: async (
    projectId: string,
    opts: { page?: number; perPage?: number } = {},
  ): Promise<CommitList> => {
    const r = await http.get<{ commits: ApiCommit[]; last_synced_at?: string | null }>(
      `/projects/${projectId}/commits`,
      { page: opts.page, per_page: opts.perPage },
    )
    return { commits: r.commits.map(mapCommit), lastSyncedAt: r.last_synced_at ?? null }
  },
}
