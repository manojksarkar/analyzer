import type { Document, ExportReadiness, ReviewStatus } from '../../types'
import { matchesReviewer } from '../../lib/docTree'
import { wordFileOutOfDate } from '../../lib/reviewStatus'
import { isUpdating } from '../../lib/wordFiles'

/* The documents list's pure rules: which rows show, and which selected rows bulk approve takes. */

export interface DocListFilters {
  /** 'All' or one process. */
  process: string
  /** Empty: every state. */
  statuses: ReadonlySet<ReviewStatus>
  /** A reviewer's user id, `none` (Needs a reviewer) or '' (every reviewer). */
  reviewer: string
  search: string
}

export function filterDocuments(docs: Document[], f: DocListFilters): Document[] {
  const q = f.search.trim().toLowerCase()
  return docs.filter((d) => {
    if (f.process !== 'All' && d.process !== f.process) return false
    if (f.statuses.size > 0 && !f.statuses.has(d.status)) return false
    if (!matchesReviewer(d, f.reviewer)) return false
    if (q && !d.name.toLowerCase().includes(q)) return false
    return true
  })
}

export interface BulkApprovePlan {
  /** Ready for approval, with a Word file that has every correction: these are approved. */
  ready: Document[]
  /** Not approved here, and why. */
  skipped: { doc: Document; reason: string }[]
  /** Ready for approval, but whether the Word file is up to date is still being read. */
  checking: Document[]
  /** Ready for approval, but its Word file is out of date or updating: the dialog offers the
   *  update (WORD_FILE_UPDATES D10, "Update them"); approved once it is up to date. */
  behind: Document[]
}

/**
 * Which of the selected documents "Approve…" approves (A9 takes only Ready for approval, each
 * guarded as A6: its Word file must be up to date). R9 for the version lists the out-of-date
 * files (`outOfDate`); an API from before it says only `stale`, and then each candidate's own R9
 * (A15) is read — unless the version is up to date.
 */
export function bulkApprovePlan(
  selected: Document[],
  ctx: {
    /** R9 for the whole version. */
    versionReadiness?: ExportReadiness
    /** R9 per document (A15), by document id (an older API only). */
    readinessById: Record<string, ExportReadiness | undefined>
    /** Documents whose R9 could not be read. */
    failed?: ReadonlySet<string>
  },
): BulkApprovePlan {
  const plan: BulkApprovePlan = { ready: [], skipped: [], checking: [], behind: [] }
  const r9 = ctx.versionReadiness
  const listed = r9?.outOfDate
  const versionUpToDate = !!r9 && !wordFileOutOfDate(r9)
  for (const doc of selected) {
    if (doc.status === 'approved') plan.skipped.push({ doc, reason: 'already approved' })
    else if (doc.status !== 'submitted') plan.skipped.push({ doc, reason: 'not ready for approval' })
    else if (isUpdating(r9, doc)) plan.behind.push(doc)
    else if (listed) (listed.some((f) => f.documentId === doc.id) ? plan.behind : plan.ready).push(doc)
    else if (versionUpToDate) plan.ready.push(doc)
    else {
      const r = ctx.readinessById[doc.id]
      if (ctx.failed?.has(doc.id)) plan.skipped.push({ doc, reason: 'its Word file could not be checked' })
      else if (!r) plan.checking.push(doc)
      else if (wordFileOutOfDate(r)) plan.behind.push(doc)
      else plan.ready.push(doc)
    }
  }
  return plan
}
