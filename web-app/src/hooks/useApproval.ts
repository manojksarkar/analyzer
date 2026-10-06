import { useMutation, useQueries, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { approvalApi, reviewApi } from '../services/api'
import { projectKeys } from './useProjects'
import { notifKeys } from './useNotifications'
import { readinessPollMs } from '../lib/wordFiles'
import { mapWordFileRefusal } from '../services/mappers'
import { toast } from '../components/ui/Toast'
import { ApiError } from '../lib/http'
import { cap, outOfDateWhy, submitBlockedSentence, type Wording } from '../lib/wordFiles'
import type { Document, ExportReadiness, SubmitWordFile } from '../types'

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

/** A15: R9 for one document, polled while an update writes Word files (Approve turns on when its
 *  file is written). */
export function useDocumentReadiness(projectId: string, versionId: string | undefined, docId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.documentReadiness(projectId, versionId ?? '', docId ?? ''),
    queryFn: () => reviewApi.readiness(projectId, versionId as string, docId),
    enabled: !!projectId && !!versionId && !!docId,
    refetchInterval: (q) => readinessPollMs(q.state.data),
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
  STALE_EXPORT: 'Its Word file is out of date.',
  WORD_FILE_UPDATING: 'Its Word file is updating.',
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
      // STALE_EXPORT says why (A6: `why`, `corrections`, `pictures`, `layer`), as R9 does.
      if (e.code === 'STALE_EXPORT') {
        // An older server sends no `why`: its message says it.
        const why = outOfDateWhy(mapWordFileRefusal(e.extra))
        return why ? `${known} ${cap(why)}.` : e.message ? `${known} ${e.message}` : known
      }
      return known
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
  // R9 of every version (an approval moves a file to "Approved, not changed"; Submit can start an
  // update): only its readiness reads, not the corrections lists beside them.
  qc.invalidateQueries({
    queryKey: [...projectKeys.detail(projectId), 'review'],
    predicate: (q) => q.queryKey[4] === 'readiness',
  })
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

/** What Submit says (A5's `word_file`): its Word file had every correction; it is updating now
 *  (the server started it, no second dialog); or a run held the version, so it stays out of date
 *  until that ends — the submit went through all the same. */
export function submitSaid(wordFile: SubmitWordFile | null, words: Wording): Said {
  if (!wordFile || wordFile.state === 'up_to_date') return ['Submitted for approval.', 'The admins are notified.']
  if (wordFile.state === 'updating') return ['Submitted.', 'Its Word file is updating.']
  return ['Submitted.', submitBlockedSentence(wordFile.blockedBy, words)]
}

/** A5: In review / Changes requested → Ready for approval, with what the reviewer checked. When its
 *  Word file is out of date the server starts its update; R9 is read again (invalidateReview), so
 *  the reader shows *Updating…*. `words` names the version and components in the toast. */
export function useSubmitForApproval(projectId: string) {
  return useReviewMutation(projectId,
    ({ docId, comment }: { docId: string; comment: string; words: Wording }) => approvalApi.submit(projectId, docId, comment),
    { title: 'Not submitted', success: (r, v) => submitSaid(r.wordFile, v.words) })
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
        // A9: each skipped one carries A6's refusal — its code in words where it has some.
        const said = r.skipped.map((s) => CODE_MESSAGES[s.code] ?? s.message).filter(Boolean)[0]
        const skipped = r.skipped.length
          ? ` ${plural(r.skipped.length, 'document')} skipped: ${(said ?? 'not ready for approval').replace(/\.$/, '')}.`
          : ''
        return r.done.length
          ? [`Approved ${plural(r.done.length, 'document')}.`, `Each is locked, and its reviewer is notified.${skipped}`]
          : ['Nothing approved.', skipped.trim() || undefined, 'info']
      },
    })
}
