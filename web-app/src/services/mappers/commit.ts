import type { Commit, PageState } from '../../types'
import { relativeTime, shortSha } from '../../lib/format'

export interface ApiCommit {
  sha: string; message: string; author: string; committed_at: string
  branch: string; doc_status: string; version: string | null; is_current: boolean
}

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
