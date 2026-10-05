import { http } from '../../lib/http'
import type { Document, ReviewEvent } from '../../types'
import {
  mapDocument, mapReviewEvent, mapSkipped,
  type ApiDocument, type ApiReviewEvent, type Skipped,
} from '../mappers'

/* Review and approval (docs/spec/REVIEW_APPROVE_API_SPEC.md, routes A1–A11). A document has one
   reviewer; it moves In review → Ready for approval → Approved (or back as Changes requested)
   only through these calls. Each one that changes a document answers with it as it now is. */

const docs = (pid: string) => `/projects/${pid}/documents`
const one = async (p: Promise<{ document: ApiDocument }>): Promise<Document> => mapDocument((await p).document)

export interface BatchResult { done: string[]; skipped: Skipped[] }

export const approvalApi = {
  /** A1: make one member the reviewer, replacing any. */
  assign: (pid: string, docId: string, userId: string): Promise<Document> =>
    one(http.post(`${docs(pid)}/${docId}/assignments`, { user_id: userId })),
  /** A2: the same for several documents; an approved one is skipped. */
  assignBatch: async (pid: string, docIds: string[], userId: string): Promise<BatchResult> => {
    const r = await http.post<{ assigned: string[]; skipped: { document_id: string; code: string; message: string }[] }>(
      `${docs(pid)}/assignments/batch`, { document_ids: docIds, user_id: userId })
    return { done: r.assigned ?? [], skipped: mapSkipped(r.skipped ?? []) }
  },
  /** A3: remove the reviewer. */
  unassign: (pid: string, docId: string, userId: string): Promise<void> =>
    http.del(`${docs(pid)}/${docId}/assignments/${userId}`),
  /** A4: a developer becomes the reviewer of a document that has none. */
  claim: (pid: string, docId: string): Promise<Document> =>
    one(http.post(`${docs(pid)}/${docId}/assignments/self`)),
  /** A5: In review / Changes requested → Ready for approval. The comment is required. */
  submit: (pid: string, docId: string, comment: string): Promise<Document> =>
    one(http.post(`${docs(pid)}/${docId}/submit-review`, { comment })),
  /** A6: Ready for approval (or In review: direct) → Approved. */
  approve: (pid: string, docId: string, comment: string | null): Promise<Document> =>
    one(http.post(`${docs(pid)}/${docId}/approve`, { comment })),
  /** A7: Ready for approval → Changes requested. The comment is required. */
  requestChanges: (pid: string, docId: string, comment: string): Promise<Document> =>
    one(http.post(`${docs(pid)}/${docId}/request-changes`, { comment })),
  /** A8: Approved → In review, with a reason; the reviewer stays. */
  reopen: (pid: string, docId: string, reason: string): Promise<Document> =>
    one(http.post(`${docs(pid)}/${docId}/reopen`, { reason })),
  /** A9: approve the listed documents that are Ready for approval; the rest are reported. */
  approveMany: async (pid: string, docIds: string[], comment: string | null = null): Promise<BatchResult> => {
    const r = await http.post<{ approved: string[]; skipped: { document_id: string; code: string; message: string }[] }>(
      `${docs(pid)}/approve-all`, { document_ids: docIds, comment })
    return { done: r.approved ?? [], skipped: mapSkipped(r.skipped ?? []) }
  },
  /** A10: one document's record, newest first. */
  events: async (pid: string, docId: string): Promise<ReviewEvent[]> => {
    const r = await http.get<{ events: ApiReviewEvent[] }>(`${docs(pid)}/${docId}/events`)
    return r.events.map(mapReviewEvent)
  },
  /** A11: the project's record, newest first (each event names its document). */
  projectEvents: async (
    pid: string,
    filters: { versionId?: string; documentId?: string; limit?: number } = {},
  ): Promise<ReviewEvent[]> => {
    const r = await http.get<{ events: ApiReviewEvent[] }>(`/projects/${pid}/review-events`, {
      version_id: filters.versionId, document_id: filters.documentId, limit: filters.limit,
    })
    return r.events.map(mapReviewEvent)
  },
}
