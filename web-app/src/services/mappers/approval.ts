import { z } from 'zod'
import type {
  DocReview, ReviewEvent, ReviewEventKind, UserRef, VersionReview,
} from '../../types'

/* Review and approval (docs/spec/REVIEW_APPROVE_API_SPEC.md §2): who reviews a document, its
   comments, its approval, and the record of every step. snake_case on the wire, like the rest of
   the documents API. */

export const ApiUserRefSchema = z.object({
  user_id: z.string(), name: z.string(), initials: z.string(),
})
export type ApiUserRef = z.infer<typeof ApiUserRefSchema>

export const ApiReviewEventSchema = z.object({
  id: z.string(),
  document_id: z.string(),
  version_id: z.string(),
  kind: z.string(),
  actor: ApiUserRefSchema.nullable(),
  at: z.string(),
  comment: z.string().nullable(),
  payload: z.record(z.string(), z.unknown()).nullable(),
  // A11 (the project's feed) names the document.
  document: z.object({ id: z.string(), name: z.string(), process: z.string() }).optional(),
})
export type ApiReviewEvent = z.infer<typeof ApiReviewEventSchema>

export const ApiDocReviewSchema = z.object({
  comment: z.string().nullable(),
  changes_comment: z.string().nullable(),
  approved_by: ApiUserRefSchema.nullable(),
  approved_at: z.string().nullable(),
  approval_comment: z.string().nullable(),
  docx_sha256: z.string().nullable(),
  carried_from: z.object({ version_id: z.string(), tag: z.string() }).nullable(),
  last_event: ApiReviewEventSchema.nullable(),
})
export type ApiDocReview = z.infer<typeof ApiDocReviewSchema>

export const ApiVersionReviewSchema = z.object({
  documents: z.number(),
  approved: z.number(),
  in_review: z.number(),
  submitted: z.number(),
  changes_requested: z.number(),
  carried: z.number(),
  approved_by: ApiUserRefSchema.nullable(),
  approved_at: z.string().nullable(),
})
export type ApiVersionReview = z.infer<typeof ApiVersionReviewSchema>

/** A2 / A9: what was done, and what was skipped and why. */
export const ApiSkippedSchema = z.object({
  document_id: z.string(), code: z.string(), message: z.string(),
})
export const ApiAssignBatchSchema = z.object({
  assigned: z.array(z.string()), skipped: z.array(ApiSkippedSchema),
})
export const ApiApproveManySchema = z.object({
  approved: z.array(z.string()), skipped: z.array(ApiSkippedSchema),
})
export const ApiEventsSchema = z.object({ events: z.array(ApiReviewEventSchema) })

export interface Skipped { documentId: string; code: string; message: string }

export function mapUserRef(u: ApiUserRef | null | undefined): UserRef | null {
  return u ? { userId: u.user_id, name: u.name, initials: u.initials } : null
}

export function mapReviewEvent(e: ApiReviewEvent): ReviewEvent {
  return {
    id: e.id,
    documentId: e.document_id,
    versionId: e.version_id,
    kind: e.kind as ReviewEventKind,
    actor: mapUserRef(e.actor),
    at: e.at,
    comment: e.comment ?? null,
    payload: e.payload ?? {},
    ...(e.document ? { document: e.document } : {}),
  }
}

/** No review on the wire (an older API): nothing said, nothing approved. */
export const EMPTY_REVIEW: DocReview = {
  comment: null, changesComment: null, approvedBy: null, approvedAt: null, approvalComment: null,
  docxSha256: null, carriedFrom: null, lastEvent: null,
}

export function mapDocReview(r: ApiDocReview | null | undefined): DocReview {
  if (!r) return EMPTY_REVIEW
  return {
    comment: r.comment ?? null,
    changesComment: r.changes_comment ?? null,
    approvedBy: mapUserRef(r.approved_by),
    approvedAt: r.approved_at ?? null,
    approvalComment: r.approval_comment ?? null,
    docxSha256: r.docx_sha256 ?? null,
    carriedFrom: r.carried_from ? { versionId: r.carried_from.version_id, tag: r.carried_from.tag } : null,
    lastEvent: r.last_event ? mapReviewEvent(r.last_event) : null,
  }
}

export function mapVersionReview(r: ApiVersionReview | null | undefined): VersionReview | null {
  if (!r) return null
  return {
    documents: r.documents,
    approved: r.approved,
    inReview: r.in_review,
    submitted: r.submitted,
    changesRequested: r.changes_requested,
    carried: r.carried,
    approvedBy: mapUserRef(r.approved_by),
    approvedAt: r.approved_at ?? null,
  }
}

export function mapSkipped(s: z.infer<typeof ApiSkippedSchema>[]): Skipped[] {
  return s.map((x) => ({ documentId: x.document_id, code: x.code, message: x.message }))
}
