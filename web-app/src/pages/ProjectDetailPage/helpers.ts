import type { Document, JobPhase, JobPhaseStatus, ReviewEvent, ReviewStatus, Version } from '../../types'

/* ── Job formatting helpers ── */
export const PHASE_UI: Record<JobPhaseStatus, 'done' | 'active' | 'pending'> = {
  done: 'done', running: 'active', pending: 'pending', failed: 'pending',
}
export function fmtClock(total: number): string {
  const s = Math.max(0, total)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(sec)}`
}
export function fmtEta(total: number): string {
  if (total >= 3600) return `${Math.floor(total / 3600)}h ${Math.round((total % 3600) / 60)}m`
  if (total >= 60) return `${Math.round(total / 60)}m`
  return `${total}s`
}
export function phaseTime(p: JobPhase): string {
  if (p.status === 'done') return p.durationSeconds != null ? `Done · ${fmtEta(p.durationSeconds)}` : 'Done'
  if (p.status === 'running') return 'Running...'
  if (p.status === 'failed') return 'Failed'
  return 'Pending'
}
export function fmtStart(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/* ── Review and approval on the Overview (project-detail.html) ── */

/** The admin's three queues: what waits for their decision, what nobody reviews, what went
 *  back to its reviewer. */
export function reviewQueues(docs: Document[]) {
  return {
    ready: docs.filter((d) => d.status === 'submitted'),
    needsReviewer: docs.filter((d) => !d.reviewer && d.status !== 'approved'),
    changes: docs.filter((d) => d.status === 'changes_requested'),
  }
}

const URGENCY: Record<ReviewStatus, number> = { changes_requested: 0, in_review: 1, submitted: 2, approved: 3 }

/** The documents I review, what needs me first; and how many need me now. */
export function myReviews(docs: Document[], meId: string): { docs: Document[]; toDo: number } {
  const mine = docs
    .filter((d) => !!meId && d.reviewer?.userId === meId)
    .sort((a, b) => URGENCY[a.status] - URGENCY[b.status])
  return { docs: mine, toDo: mine.filter((d) => d.status === 'in_review' || d.status === 'changes_requested').length }
}

/** One line of Last actions: an event, or several run events of one version folded into one. */
export interface ActionLine {
  event: ReviewEvent
  /** How many events it stands for (a run generates or carries one per document). */
  count: number
}

/**
 * A run writes one `generated` or `carried` event per document; the feed shows each run's as one
 * line ("The run generated 12 documents of v1.2.0") rather than a screenful.
 */
export function foldRunEvents(events: ReviewEvent[]): ActionLine[] {
  const out: ActionLine[] = []
  for (const e of events) {
    const prev = out[out.length - 1]
    const isRun = e.kind === 'generated' || e.kind === 'carried'
    if (isRun && prev && prev.event.kind === e.kind && prev.event.versionId === e.versionId) prev.count += 1
    else out.push({ event: e, count: 1 })
  }
  return out
}

/** What a developer's Last actions show: their own steps, and any on the documents they review
 *  or were given or taken. An admin sees all. */
export function concernsMe(e: ReviewEvent, myDocIds: ReadonlySet<string>, meId: string): boolean {
  if (e.kind === 'generated' || e.kind === 'carried') return true
  if (e.actor?.userId === meId) return true
  if (e.payload.to_user_id === meId || e.payload.from_user_id === meId || e.payload.user_id === meId) return true
  return myDocIds.has(e.documentId)
}

/* ── Run Analysis ── */

/** Why a version name cannot be used, or null. The API requires one, unique in the project
 *  (`VERSION_EXISTS`); saying so here keeps Start from failing after the click. */
export function versionNameProblem(name: string, versions?: Version[]): string | null {
  const n = name.trim()
  if (!n) return 'Name the version.'
  if ((versions ?? []).some((v) => v.tag === n)) return `${n} already exists in this project. Choose another name.`
  return null
}
