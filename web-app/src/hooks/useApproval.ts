import { useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { approvalApi, reviewApi } from '../services/api'
import { projectKeys } from './useProjects'
import { notifKeys } from './useNotifications'
import { reexportActive } from './useReview'
import { toast } from '../components/ui/Toast'
import { ApiError } from '../lib/http'
import type { Document, ExportReadiness } from '../types'

/* Review and approval (docs/spec/REVIEW_APPROVE_API_SPEC.md): reads A10, A11, A15 and the
   mutations A1–A9. A mutation can change the document, its version's status (approved when every
   document is), the project's status, the counts and the record, and it notifies someone: each
   refreshes all of those. */

/* ── Reads ─────────────────────────────────────────────────────────────── */

/** A10: one document's record, newest first. */
export function useDocumentEvents(projectId: string, docId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.documentEvents(projectId, docId ?? ''),
    queryFn: () => approvalApi.events(projectId, docId as string),
    enabled: !!projectId && !!docId,
  })
}

/** A11: the project's record, newest first, for one version (or every version). */
export function useReviewEvents(projectId: string, versionId?: string, limit = 50) {
  return useQuery({
    queryKey: projectKeys.reviewEvents(projectId, versionId),
    queryFn: () => approvalApi.projectEvents(projectId, { versionId, limit }),
    enabled: !!projectId,
  })
}

/** A15: R9 for one document's component and type, polled while a re-export runs. */
export function useDocumentReadiness(projectId: string, versionId: string | undefined, docId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.documentReadiness(projectId, versionId ?? '', docId ?? ''),
    queryFn: () => reviewApi.readiness(projectId, versionId as string, docId),
    enabled: !!projectId && !!versionId && !!docId,
    refetchInterval: (q) => (reexportActive(q.state.data) ? 2500 : false),
  })
}

/** A15 for several documents (the bulk-approve dialog), read only while `enabled`. */
export function useDocumentsReadiness(projectId: string, docs: Pick<Document, 'id' | 'versionId'>[], enabled: boolean) {
  return useQueries({
    queries: docs.map((d) => ({
      queryKey: projectKeys.documentReadiness(projectId, d.versionId ?? '', d.id),
      queryFn: () => reviewApi.readiness(projectId, d.versionId as string, d.id),
      enabled: enabled && !!projectId && !!d.versionId,
    })),
    combine: (results) => {
      const byId: Record<string, ExportReadiness | undefined> = {}
      const failed = new Set<string>()
      docs.forEach((d, i) => {
        byId[d.id] = results[i]?.data
        if (results[i]?.isError) failed.add(d.id)
      })
      return { byId, failed, isLoading: results.some((r) => r.isLoading) }
    },
  })
}

/* ── Errors ────────────────────────────────────────────────────────────── */

/** The 409 / 422 codes of the review routes, in words (A1–A9). */
const CODE_MESSAGES: Record<string, string> = {
  WRONG_STATE: 'Its state changed since this page read it. The page now shows where it is.',
  STALE_EXPORT: 'Its Word file does not have every correction yet: re-export first, then approve.',
  DOCUMENT_APPROVED: 'It is approved, so it is locked. An admin reopens it first.',
  HAS_REVIEWER: 'Someone already reviews it.',
  NO_REVIEWER: 'It needs a reviewer first.',
  NOT_A_MEMBER: 'That person is not an active member of this project.',
}

/** What a failed review call says to the user: its code in words, else the server's message. */
export function approvalErrorMessage(e: unknown): string {
  if (e instanceof ApiError) {
    const known = e.code ? CODE_MESSAGES[e.code] : undefined
    if (known) {
      // STALE_EXPORT's message says why (which corrections are missing); keep it.
      return e.code === 'STALE_EXPORT' && e.message ? `${known} ${e.message}` : known
    }
    if (e.status === 403) return 'You cannot do this on this document.'
    return e.message
  }
  return e instanceof Error ? e.message : String(e)
}

/* ── Mutations ─────────────────────────────────────────────────────────── */

/** Everything a review step can change. Not the rendered pages: their content stays the same. */
export function invalidateReview(qc: QueryClient, projectId: string) {
  qc.invalidateQueries({
    queryKey: projectKeys.documentsAll(projectId),
    predicate: (q) => q.queryKey[3] !== 'render',
  })
  qc.invalidateQueries({ queryKey: projectKeys.versions(projectId) })
  qc.invalidateQueries({ queryKey: projectKeys.reviewEventsAll(projectId) })
  // The project's status follows its latest version: its own read and the projects list.
  qc.invalidateQueries({ queryKey: projectKeys.detail(projectId), exact: true })
  qc.invalidateQueries({ queryKey: projectKeys.lists })
  qc.invalidateQueries({ queryKey: notifKeys.all })
}

/** A toast: its title, its line, and whether it is news rather than a success. */
type Said = [string, string?, 'info'?]

function useReviewMutation<V, R>(
  projectId: string,
  fn: (v: V) => Promise<R>,
  opts: { title: string; success: (r: R, v: V) => Said },
) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: (r, v) => {
      invalidateReview(qc, projectId)
      const [title, description, info] = opts.success(r, v)
      if (info) toast.info(title, description)
      else toast.success(title, description)
    },
    onError: (e: Error) => {
      // A 409 means the page is behind the server: read it again, so it shows the truth.
      if (e instanceof ApiError && e.status === 409) invalidateReview(qc, projectId)
      toast.error(opts.title, approvalErrorMessage(e))
    },
  })
}

const docLabel = (d: Pick<Document, 'name' | 'process'>) => `${d.name} (${d.process})`
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

/** A1: one member reviews one document, replacing whoever did. */
export function useAssignReviewer(projectId: string) {
  return useReviewMutation(projectId,
    ({ docId, userId }: { docId: string; userId: string; name?: string }) => approvalApi.assign(projectId, docId, userId),
    {
      title: 'Not assigned',
      success: (d) => [`${d.reviewer?.name ?? 'The reviewer'} reviews ${docLabel(d)} now.`, 'They get a notification.'],
    })
}

/** A2: one member reviews several documents. */
export function useAssignReviewerBatch(projectId: string) {
  return useReviewMutation(projectId,
    ({ docIds, userId }: { docIds: string[]; userId: string; name: string }) =>
      approvalApi.assignBatch(projectId, docIds, userId),
    {
      title: 'Not assigned',
      success: (r, v) => {
        const skipped = r.skipped.length ? ` ${plural(r.skipped.length, 'document')} skipped: ${r.skipped[0].message}` : ''
        return r.done.length
          ? [`${v.name} reviews ${plural(r.done.length, 'document')} now.`, `They get a notification.${skipped}`]
          : ['Nothing assigned.', skipped.trim() || undefined, 'info']
      },
    })
}

/** A3: the document has no reviewer again. */
export function useRemoveReviewer(projectId: string) {
  return useReviewMutation(projectId,
    ({ docId, userId }: { docId: string; userId: string }) => approvalApi.unassign(projectId, docId, userId),
    { title: 'Reviewer not removed', success: () => ['Reviewer removed.', 'It needs a reviewer again.'] })
}

/** A4: a developer becomes the reviewer of a document nobody reviews. */
export function useClaimDocument(projectId: string) {
  return useReviewMutation(projectId,
    (docId: string) => approvalApi.claim(projectId, docId),
    {
      title: 'Could not claim',
      success: (d) => [`You review ${docLabel(d)} now.`, 'The admins are notified. Submit it for approval when you are done.'],
    })
}

/** A5: In review / Changes requested → Ready for approval, with what the reviewer checked. */
export function useSubmitForApproval(projectId: string) {
  return useReviewMutation(projectId,
    ({ docId, comment }: { docId: string; comment: string }) => approvalApi.submit(projectId, docId, comment),
    { title: 'Not submitted', success: () => ['Submitted for approval.', 'The admins are notified.'] })
}

/** A6: approve one document (from Ready for approval, or directly from In review). */
export function useApproveDocument(projectId: string) {
  return useReviewMutation(projectId,
    ({ docId, comment }: { docId: string; comment: string | null }) => approvalApi.approve(projectId, docId, comment),
    { title: 'Not approved', success: (d) => [`${docLabel(d)} is approved.`, 'It is locked, and its reviewer is notified.'] })
}

/** A7: back to its reviewer, with what needs to change. */
export function useRequestChanges(projectId: string) {
  return useReviewMutation(projectId,
    ({ docId, comment }: { docId: string; comment: string }) => approvalApi.requestChanges(projectId, docId, comment),
    {
      title: 'Not sent back',
      success: (d) => ['Sent back to its reviewer.',
        `${d.reviewer?.name ?? 'The reviewer'} is notified and sees your comment at the top of the document.`],
    })
}

/** A8: Approved → In review, with a reason; the reviewer stays. */
export function useReopenDocument(projectId: string) {
  return useReviewMutation(projectId,
    ({ docId, reason }: { docId: string; reason: string }) => approvalApi.reopen(projectId, docId, reason),
    {
      title: 'Not reopened',
      success: (d) => [`${docLabel(d)} is in review again.`, 'Corrections are allowed. The approval stays in its activity.'],
    })
}

/** A9: approve the listed documents that are Ready for approval; the server reports the rest. */
export function useApproveDocuments(projectId: string) {
  return useReviewMutation(projectId,
    ({ docIds, comment }: { docIds: string[]; comment?: string | null }) =>
      approvalApi.approveMany(projectId, docIds, comment ?? null),
    {
      title: 'Not approved',
      success: (r) => {
        const skipped = r.skipped.length
          ? ` ${plural(r.skipped.length, 'document')} skipped: ${r.skipped.map((s) => s.message).filter(Boolean)[0] ?? 'not ready for approval'}.`
          : ''
        return r.done.length
          ? [`Approved ${plural(r.done.length, 'document')}.`, `Each is locked, and its reviewer is notified.${skipped}`]
          : ['Nothing approved.', skipped.trim() || undefined, 'info']
      },
    })
}
