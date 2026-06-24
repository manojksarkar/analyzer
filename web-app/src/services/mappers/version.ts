import type { Version, PageState, VersionStatus } from '../../types'
import { formatDate, shortSha } from '../../lib/format'

export interface ApiVersion {
  id: string; tag: string; commit_sha: string; branch: string; description: string
  status: string; docs_count: number; created_by: string; created_at: string
}

const versionPageState = (status: string): PageState =>
  status === 'approved' ? 'complete' : 'in_review'

export function mapVersion(v: ApiVersion): Version {
  return {
    id: v.id,
    tag: v.tag,
    status: v.status as VersionStatus,
    description: v.description,
    sha: v.commit_sha,
    shortSha: shortSha(v.commit_sha),
    branch: v.branch,
    docsCount: v.docs_count,
    date: formatDate(v.created_at) ?? '',
    pageState: versionPageState(v.status),
  }
}
