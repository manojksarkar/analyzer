import { z } from 'zod'
import type { Version, PageState, VersionRunInfo, VersionStatus } from '../../types'
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
  // How it was made (`versions.run_report`); absent from an older API.
  run: z.object({
    made_by: z.string().nullable().optional(),
    scope: z.object({ type: z.string().nullable().optional(), names: z.array(z.string()).nullable().optional() })
      .nullable().optional(),
    doc_type: z.string().nullable().optional(),
    model_only: z.boolean().nullable().optional(),
  }).nullable().optional(),
})
export type ApiVersion = z.infer<typeof ApiVersionSchema>

function mapRunInfo(r: ApiVersion['run']): VersionRunInfo | null {
  if (!r) return null
  const madeBy = r.made_by === 'web' || r.made_by === 'cli' ? r.made_by : null
  const docType = r.doc_type === 'swe3' || r.doc_type === 'swe4' || r.doc_type === 'all' ? r.doc_type : null
  return {
    madeBy,
    scope: r.scope ? { type: r.scope.type || 'project', names: r.scope.names ?? [] } : null,
    docType,
    modelOnly: !!r.model_only,
  }
}

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
    run: mapRunInfo(v.run),
  }
}
