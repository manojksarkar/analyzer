import { z } from 'zod'
import type { Version, PageState, VersionStatus } from '../../types'
import { formatDate, shortSha } from '../../lib/format'
import { versionStatusOf } from '../../lib/reviewStatus'
import { ApiVersionReviewSchema, mapVersionReview } from './approval'

// `status` is derived by the server from the version's documents (REVIEW_APPROVE_API_SPEC A14):
// approved when every one is, else in review; `draft` while it has none.
export const ApiVersionSchema = z.object({
  // A version the CLI made has no branch, description or author: tolerated, so one such version
  // does not empty the whole list.
  id: z.string(), tag: z.string(), commit_sha: z.string(), branch: z.string().nullable(), description: z.string().nullable(),
  status: z.string(), docs_count: z.number(), created_by: z.string().nullable(), created_at: z.string(),
  warnings: z.array(z.string()).optional(),
  review: ApiVersionReviewSchema,
})
export type ApiVersion = z.infer<typeof ApiVersionSchema>

// A `draft` version has no documents: its run is still going, or it was only tagged.
const versionPageState = (status: VersionStatus): PageState =>
  status === 'approved' ? 'complete' : status === 'draft' ? 'never' : 'in_review'

export function mapVersion(v: ApiVersion): Version {
  const status = versionStatusOf(v.status)
  return {
    id: v.id,
    tag: v.tag,
    status,
    description: v.description ?? '',
    sha: v.commit_sha,
    shortSha: shortSha(v.commit_sha),
    branch: v.branch ?? '',
    docsCount: v.docs_count,
    date: formatDate(v.created_at) ?? '',
    pageState: versionPageState(status),
    warnings: v.warnings ?? [],
    review: mapVersionReview(v.review),
  }
}
