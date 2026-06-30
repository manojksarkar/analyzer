import { z } from 'zod'
import type { Version, PageState, VersionStatus } from '../../types'
import { formatDate, shortSha } from '../../lib/format'

export const ApiVersionSchema = z.object({
  id: z.string(), tag: z.string(), commit_sha: z.string(), branch: z.string(), description: z.string(),
  status: z.string(), docs_count: z.number(), created_by: z.string(), created_at: z.string(),
})
export type ApiVersion = z.infer<typeof ApiVersionSchema>

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
