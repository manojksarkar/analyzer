import type {
  Document, PageState, ReviewEvent, ReviewEventKind, ReviewStatus, VersionStatus,
} from '../types'

/* Review and approval: the one place a state's word, icon and colours live
   (docs/design/REVIEW_APPROVE_DESIGN.md "One word per state"). A document has four states; a
   version or a page adds its own (not run, running, stale). Every badge, bar, dot and filter reads
   this map, through components/ui/StatusBadge for a badge. */

export type StatusKey = ReviewStatus | 'not_run' | 'running' | 'stale'

export interface StatusMeta {
  label: string
  icon: string
  /** A badge's background, text and border. */
  badge: string
  /** A dot's, or a bar segment's, background. */
  dot: string
  /** The text colour. */
  text: string
  /** The colour as a value, for what is drawn with data-driven sizes (bar widths, donut arcs). */
  hex: string
}

export const STATUS_META: Record<StatusKey, StatusMeta> = {
  in_review: {
    label: 'In review', icon: 'rate_review',
    badge: 'bg-[#fff8e6] text-[#b45309] border-amber', dot: 'bg-amber', text: 'text-[#b45309]', hex: '#f59e0b',
  },
  submitted: {
    label: 'Ready for approval', icon: 'pending_actions',
    badge: 'bg-surface-container text-secondary border-[#8ab0f0]', dot: 'bg-secondary-container', text: 'text-secondary', hex: '#2170e4',
  },
  changes_requested: {
    label: 'Changes requested', icon: 'undo',
    badge: 'bg-[#fff1f0] text-error border-[#f5a3a3]', dot: 'bg-error', text: 'text-error', hex: '#ba1a1a',
  },
  approved: {
    label: 'Approved', icon: 'check_circle',
    badge: 'bg-[#f0fdf9] text-[#00a572] border-[#86efac]', dot: 'bg-[#00a572]', text: 'text-[#00a572]', hex: '#00a572',
  },
  not_run: {
    label: 'Not run', icon: 'radio_button_unchecked',
    badge: 'bg-[#f3f4f6] text-outline border-[#e2e3e8]', dot: 'bg-outline', text: 'text-outline', hex: '#74777d',
  },
  running: {
    label: 'Running', icon: 'sync',
    badge: 'bg-surface-container text-secondary border-[#bfcfff]', dot: 'bg-secondary', text: 'text-secondary', hex: '#0058be',
  },
  stale: {
    label: 'Stale', icon: 'warning',
    badge: 'bg-[#fffbeb] text-[#d97706] border-amber', dot: 'bg-amber', text: 'text-[#d97706]', hex: '#d97706',
  },
}

/** The four document states in their life's order (filters, legends). */
export const REVIEW_STATUSES: ReviewStatus[] = ['in_review', 'submitted', 'changes_requested', 'approved']
/** Bars and donuts: approved first, as the mockups draw them. */
export const REVIEW_ORDER: ReviewStatus[] = ['approved', 'submitted', 'changes_requested', 'in_review']

/** A document's state from the wire. An unknown one (an older API's `complete`, `never`) reads as
 *  the nearest of the four rather than breaking a page. */
export function reviewStatusOf(raw: string | null | undefined): ReviewStatus {
  if (raw === 'approved' || raw === 'complete') return 'approved'
  if (raw === 'submitted' || raw === 'changes_requested') return raw
  return 'in_review'
}

/** A version's status from the wire: derived by the server (approved when every document is). */
export function versionStatusOf(raw: string | null | undefined): VersionStatus {
  if (raw === 'approved' || raw === 'complete') return 'approved'
  if (raw === 'draft') return 'draft'
  return 'in_review'
}

export function pageStateStatus(s: PageState): StatusKey {
  if (s === 'complete') return 'approved'
  if (s === 'never') return 'not_run'
  return s
}

/** A version's badge: a draft is "Running" while its run goes, else "Not run". */
export function versionStatusKey(s: VersionStatus, running = false): StatusKey {
  if (s === 'draft') return running ? 'running' : 'not_run'
  return s
}

/** What a reviewer does next, per state (a developer's My reviews). */
export const NEXT_STEP: Record<ReviewStatus, string> = {
  in_review: 'Review, then submit for approval',
  submitted: 'Waiting for approval',
  changes_requested: 'Fix what the admin asked, then submit again',
  approved: 'Approved',
}

export interface ReviewCounts {
  total: number
  in_review: number
  submitted: number
  changes_requested: number
  approved: number
  /** Not approved and without a reviewer. */
  needsReviewer: number
  /** Approved because an earlier version's approval carried. */
  carried: number
}

type CountedDoc = Pick<Document, 'status' | 'reviewer'> & { review?: Pick<Document['review'], 'carriedFrom'> }

export function needsReviewer(d: Pick<Document, 'status' | 'reviewer'>): boolean {
  return !d.reviewer && d.status !== 'approved'
}

export function reviewCounts(docs: CountedDoc[]): ReviewCounts {
  const c: ReviewCounts = {
    total: docs.length, in_review: 0, submitted: 0, changes_requested: 0, approved: 0, needsReviewer: 0, carried: 0,
  }
  for (const d of docs) {
    c[d.status] += 1
    if (needsReviewer(d)) c.needsReviewer += 1
    if (d.status === 'approved' && d.review?.carriedFrom) c.carried += 1
  }
  return c
}

/** The derived status line of a version or a project: "In review · 3/6 approved", or "Approved". */
export function approvalLabel(approved: number, total: number): string {
  return total > 0 && approved === total ? 'Approved' : `In review · ${approved}/${total} approved`
}

/* ── The review record ── */

export const EVENT_META: Record<ReviewEventKind, { icon: string; dot: string; text: string }> = {
  generated:         { icon: 'play_circle',     dot: 'bg-outline-variant', text: 'text-secondary' },
  carried:           { icon: 'verified',        dot: 'bg-[#00a572]',       text: 'text-[#00a572]' },
  assigned:          { icon: 'person_add',      dot: 'bg-[#7c3aed]',       text: 'text-[#7c3aed]' },
  unassigned:        { icon: 'person_remove',   dot: 'bg-[#7c3aed]',       text: 'text-[#7c3aed]' },
  claimed:           { icon: 'front_hand',      dot: 'bg-[#7c3aed]',       text: 'text-[#7c3aed]' },
  submitted:         { icon: 'pending_actions', dot: 'bg-secondary',       text: 'text-secondary' },
  approved:          { icon: 'check_circle',    dot: 'bg-[#00a572]',       text: 'text-[#00a572]' },
  changes_requested: { icon: 'undo',            dot: 'bg-error',           text: 'text-error' },
  reopened:          { icon: 'lock_open',       dot: 'bg-[#b45309]',       text: 'text-[#b45309]' },
}

export function eventMeta(kind: string) {
  return EVENT_META[kind as ReviewEventKind] ?? EVENT_META.generated
}

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)

/**
 * What an event did, in words: `actor` (bold on screen; null for the run) and the rest.
 * `doc` names the document (the project's feed); without it the line is about "it" (the
 * document's own timeline). `nameOf` turns a user id from the payload into a name.
 */
export function describeEvent(
  e: Pick<ReviewEvent, 'kind' | 'actor' | 'payload'>,
  opts: { doc?: string; nameOf?: (userId: string) => string | undefined; meId?: string } = {},
): { actor: string | null; text: string } {
  const { doc, meId } = opts
  const who = (id: string | null, object = false): string => {
    if (!id) return object ? 'nobody' : 'Nobody'
    if (meId && id === meId) return object ? 'you' : 'You'
    return opts.nameOf?.(id) ?? 'someone'
  }
  const actor = e.actor ? (meId && e.actor.userId === meId ? 'You' : e.actor.name) : null
  const it = doc ?? 'it'
  const p = e.payload ?? {}
  switch (e.kind) {
    case 'generated': {
      const kept = str(p.kept_reviewer_from)
      const base = doc ? `${doc} was generated by the run` : 'Generated by the run'
      return { actor: null, text: kept ? `${base}; its reviewer kept from ${kept}` : base }
    }
    case 'carried': {
      const tag = str(p.from_tag) ?? 'an earlier version'
      return {
        actor: null,
        text: doc
          ? `${doc} stays approved: content unchanged since ${tag}`
          : `Approved in ${tag}. The content is unchanged, so the approval carries`,
      }
    }
    case 'assigned': {
      const from = str(p.from_user_id)
      const to = who(str(p.to_user_id), true)
      if (from) return { actor, text: `re-assigned ${it} from ${who(from, true)} to ${to}` }
      return { actor, text: doc ? `assigned ${to} to ${doc}` : `assigned ${to}` }
    }
    case 'unassigned': {
      const u = who(str(p.user_id), true)
      return { actor, text: doc ? `removed ${u} as reviewer of ${doc}` : `removed ${u} as its reviewer` }
    }
    case 'claimed':
      return { actor, text: `claimed ${it}` }
    case 'submitted':
      return { actor, text: `submitted ${it} for approval` }
    case 'approved':
      return { actor, text: p.direct === true ? `approved ${it} directly, without a submitted review` : `approved ${it}` }
    case 'changes_requested':
      return { actor, text: doc ? `requested changes to ${doc}` : 'requested changes' }
    case 'reopened':
      return { actor, text: `reopened ${it}` }
  }
  return { actor, text: String(e.kind) }
}

/** The approved Word file's hash, shortened as the screens print it. */
export function shortHash(sha: string | null | undefined): string {
  return sha ? `${sha.slice(0, 12)}…` : ''
}

/** R9: the Word file lacks corrections (or pictures still owed): it cannot be approved now. */
export function wordFileOutOfDate(r: { stale: boolean; pendingRenders: number } | null | undefined): boolean {
  return !!r && (r.stale || r.pendingRenders > 0)
}
