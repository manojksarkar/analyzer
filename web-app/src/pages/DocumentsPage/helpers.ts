import type { ComponentState, Document, ExportReadiness, ReviewStatus, VersionComponent } from '../../types'
import { matchesReviewer } from '../../lib/docTree'
import { wordFileOutOfDate } from '../../lib/reviewStatus'

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
}

/**
 * Which of the selected documents "Approve…" approves (A9 takes only Ready for approval, each
 * guarded as A6: its Word file must have every correction — R9 for its component and type).
 * When the whole version's Word files are up to date, no document needs its own check.
 */
export function bulkApprovePlan(
  selected: Document[],
  ctx: {
    /** R9 for the whole version. */
    versionReadiness?: ExportReadiness
    /** R9 per document (A15), by document id. */
    readinessById: Record<string, ExportReadiness | undefined>
    /** Documents whose R9 could not be read. */
    failed?: ReadonlySet<string>
    /** A re-export is running: nothing can be approved until it ends. */
    reexporting: boolean
  },
): BulkApprovePlan {
  const plan: BulkApprovePlan = { ready: [], skipped: [], checking: [] }
  const versionUpToDate = !!ctx.versionReadiness && !wordFileOutOfDate(ctx.versionReadiness)
  for (const doc of selected) {
    if (doc.status === 'approved') plan.skipped.push({ doc, reason: 'already approved' })
    else if (doc.status !== 'submitted') plan.skipped.push({ doc, reason: 'not ready for approval' })
    else if (ctx.reexporting) plan.skipped.push({ doc, reason: 'a re-export is running' })
    else if (versionUpToDate) plan.ready.push(doc)
    else {
      const r = ctx.readinessById[doc.id]
      if (ctx.failed?.has(doc.id)) plan.skipped.push({ doc, reason: 'its Word file could not be checked' })
      else if (!r) plan.checking.push(doc)
      else if (wordFileOutOfDate(r)) plan.skipped.push({ doc, reason: 'its Word file is missing corrections' })
      else plan.ready.push(doc)
    }
  }
  return plan
}

/** Staged generation: the version's components per layer, in the order the server gives them. */
export function componentsByLayer(comps: VersionComponent[]): [string, VersionComponent[]][] {
  const out = new Map<string, VersionComponent[]>()
  for (const c of comps) {
    const list = out.get(c.layer) ?? []
    list.push(c)
    out.set(c.layer, list)
  }
  return [...out.entries()]
}

/** Components an admin can ask for: of the model, with no documents (never asked for, or the run
 *  that was making them failed or stopped). One with documents whose re-export failed is not:
 *  making it again is a re-export. */
export const PICKABLE_STATES = new Set<ComponentState>(['not_requested', 'failed', 'stopped'])
export const pickable = (c: VersionComponent) =>
  c.inModel && PICKABLE_STATES.has(c.state) && c.documents.length === 0
