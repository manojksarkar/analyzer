import { z } from 'zod'
import type { Commit, PageState } from '../../types'
import { relativeTime, shortSha } from '../../lib/format'

export const ApiCommitSchema = z.object({
  sha: z.string(), message: z.string(), author: z.string(), committed_at: z.string(),
  branch: z.string(), doc_status: z.string(), version: z.string().nullable(), is_current: z.boolean(),
})
export type ApiCommit = z.infer<typeof ApiCommitSchema>

const commitPageState = (docStatus: string): PageState =>
  docStatus === 'approved' || docStatus === 'complete'
    ? 'complete'
    : docStatus === 'in_review'
      ? 'in_review'
      : 'never'

export function mapCommit(c: ApiCommit): Commit {
  return {
    sha: c.sha,
    shortSha: shortSha(c.sha),
    message: c.message,
    author: c.author,
    relativeTime: relativeTime(c.committed_at),
    branch: c.branch,
    versionTag: c.version ?? undefined,
    pageState: commitPageState(c.doc_status),
  }
}
