import { http } from '../../lib/http'
import type { Commit } from '../../types'
import { mapCommit, type ApiCommit } from '../mappers'

export interface CommitList {
  commits: Commit[]
  /** ISO time the commits were last synced from the repo, or null. */
  lastSyncedAt: string | null
}

/** The most commits the list route answers in one page (`per_page` ≤ 100, api/routes/commits_versions.py). */
export const COMMITS_PAGE_MAX = 100
/** A guard against an API that ignores `page`: never more than this many pages (2,000 commits). */
const COMMITS_MAX_PAGES = 20

interface CommitsPage {
  commits: ApiCommit[]
  pagination?: { page?: number; per_page?: number; total?: number }
  last_synced_at?: string | null
}

const getCommitsPage = (projectId: string, page?: number, perPage?: number) =>
  http.get<CommitsPage>(`/projects/${projectId}/commits`, { page, per_page: perPage })

export const commitsApi = {
  /** One page of commits, newest first (the API's default page size is 20). */
  list: async (
    projectId: string,
    opts: { page?: number; perPage?: number } = {},
  ): Promise<CommitList> => {
    const r = await getCommitsPage(projectId, opts.page, opts.perPage)
    return { commits: r.commits.map(mapCommit), lastSyncedAt: r.last_synced_at ?? null }
  },
  /**
   * EVERY stored commit, newest first, page after page. The route has no search, and the pickers
   * (Run modal, Subbar) filter on the client: with the first page only, a commit older than the
   * newest 20 could not be picked. Page 1 goes first — it is the read that syncs the repo — and
   * says the total; the rest are read together.
   *
   * Only page 1 must answer. A later page that fails is left out (the pickers still get the rest:
   * failing the whole list showed none, where one page used to show 20). The total is counted
   * BEFORE the sync that page 1 starts, so commits pushed meanwhile push the oldest past the
   * counted pages: while the last page read comes back full, the next is read too.
   */
  listAll: async (projectId: string): Promise<CommitList> => {
    const perPage = COMMITS_PAGE_MAX
    const first = await getCommitsPage(projectId, 1, perPage)
    const pages: ApiCommit[][] = [first.commits]
    // The page read last, when it came back (unknown when it failed), and the next page's number.
    let last: ApiCommit[] | undefined = first.commits
    let next = 2
    const total = first.pagination?.total
    if (typeof total === 'number') {
      const count = Math.min(Math.ceil(total / perPage), COMMITS_MAX_PAGES)
      const rest = await Promise.allSettled(
        Array.from({ length: Math.max(count - 1, 0) }, (_, i) => getCommitsPage(projectId, i + 2, perPage)))
      for (const r of rest) if (r.status === 'fulfilled') pages.push(r.value.commits)
      const tail = rest[rest.length - 1]
      if (tail) last = tail.status === 'fulfilled' ? tail.value.commits : undefined
      next = Math.max(count, 1) + 1
    }
    // Read on while the last page came back full — no total (an older API), or commits synced
    // after the total was counted — until a short page, one that adds nothing new, or a failure.
    const seen = new Set(pages.flat().map((c) => c.sha))
    while (last && last.length >= perPage && next <= COMMITS_MAX_PAGES) {
      let page: ApiCommit[]
      try {
        page = (await getCommitsPage(projectId, next++, perPage)).commits
      } catch {
        break
      }
      if (!page.some((c) => !seen.has(c.sha))) break
      page.forEach((c) => seen.add(c.sha))
      pages.push(page)
      last = page
    }
    // A commit synced while the pages were read shifts the rest down a place: keep each once,
    // newest first, ties by sha (the API's own order) so equal times keep one order.
    const bySha = new Map<string, ApiCommit>()
    for (const c of pages.flat()) if (!bySha.has(c.sha)) bySha.set(c.sha, c)
    const time = (c: ApiCommit) => Date.parse(c.committed_at) || 0
    const commits = [...bySha.values()].sort((a, b) =>
      time(b) - time(a) || (a.sha < b.sha ? -1 : a.sha > b.sha ? 1 : 0))
    return { commits: commits.map(mapCommit), lastSyncedAt: first.last_synced_at ?? null }
  },
}
