import type { Document } from '../../types'

/* Review and approval in the reader: what this role may do to this document now, and the one
   action the Review tab offers (docs/design/REVIEW_APPROVE_DESIGN.md "Rules";
   docs/ui-mockups/documents.html renderReviewTab). Pure, so every role and state is tested. */

/** The longest comment the review routes take (A5–A8). */
export const MAX_COMMENT = 2000

export interface ReviewCtx {
  isAdmin: boolean
  /** The signed-in user's id. */
  meId: string
  /** R9 for this document's component and type: its Word file lacks corrections. */
  wordFileStale: boolean
  /** A re-export of the version is running. */
  reexporting: boolean
}

export type ReviewVerb = 'assign' | 'claim' | 'submit' | 'approve' | 'changes' | 'reopen'

type Doc = Pick<Document, 'status' | 'reviewer'>

export function isMine(doc: Doc, ctx: Pick<ReviewCtx, 'meId'>): boolean {
  return !!ctx.meId && doc.reviewer?.userId === ctx.meId
}

/** Why this role cannot do `verb` to the document now — the reason a disabled control shows —
 *  or null when it can. The server enforces the same rules (A1–A8). */
export function whyNot(verb: ReviewVerb, doc: Doc, ctx: ReviewCtx): string | null {
  const admin = ctx.isAdmin
  switch (verb) {
    case 'assign':
      if (!admin) return 'Only an admin assigns reviewers'
      return doc.status === 'approved' ? 'Approved: reopen it first' : null
    case 'claim':
      if (admin) return 'An admin assigns instead'
      if (doc.reviewer) return 'It has a reviewer'
      return doc.status === 'approved' ? 'It is approved' : null
    case 'submit':
      if (doc.status !== 'in_review' && doc.status !== 'changes_requested') return 'It is not in review'
      if (!doc.reviewer) return 'It needs a reviewer first'
      return admin || isMine(doc, ctx) ? null : 'Only its reviewer submits it'
    case 'approve':
      if (!admin) return 'Only an admin approves'
      if (doc.status !== 'submitted' && doc.status !== 'in_review') return 'It is not waiting for approval'
      if (ctx.reexporting) return 'Wait for the re-export to finish'
      return ctx.wordFileStale ? 'Re-export first: the approved Word file must have every correction' : null
    case 'changes':
      if (!admin) return 'Only an admin requests changes'
      return doc.status !== 'submitted' ? 'Only a document ready for approval' : null
    case 'reopen':
      if (!admin) return 'Only an admin reopens'
      return doc.status !== 'approved' ? 'It is not approved' : null
  }
}

export type ReviewActionKind =
  /** The approval: who, when, the comment and the Word file's hash; Reopen for an admin. */
  | 'approved'
  /** Nobody reviews it: an admin assigns… */
  | 'assign'
  /** …a developer claims it. */
  | 'claim'
  /** Ready for approval, admin: Approve… and Request changes…. */
  | 'decide'
  /** Ready for approval, anyone else: waiting for an admin. */
  | 'wait'
  /** In review or changes requested, its reviewer or an admin: a comment and Submit for approval. */
  | 'submit'
  /** Someone else reviews it: read and download only. */
  | 'read'

export interface ReviewAction {
  kind: ReviewActionKind
  /** Why Approve (or Approve directly) is off; null when it is on. */
  approveBlocked: string | null
  /** An admin may approve straight from In review (`decide` approves the submitted review). */
  directApprove: boolean
  canReopen: boolean
  /** The heading over the comment box (`submit`). */
  submitHeading: string
}

const firstName = (name: string) => name.split(' ')[0] || name

/** The one action the Review tab offers this role, for this document, now. */
export function reviewAction(doc: Doc, ctx: ReviewCtx): ReviewAction {
  const base: ReviewAction = {
    kind: 'read',
    approveBlocked: whyNot('approve', doc, ctx),
    directApprove: false,
    canReopen: whyNot('reopen', doc, ctx) === null,
    submitHeading: '',
  }
  if (doc.status === 'approved') return { ...base, kind: 'approved' }
  if (!doc.reviewer) return { ...base, kind: ctx.isAdmin ? 'assign' : 'claim' }
  if (doc.status === 'submitted') return { ...base, kind: ctx.isAdmin ? 'decide' : 'wait' }
  if (ctx.isAdmin || isMine(doc, ctx)) {
    return {
      ...base,
      kind: 'submit',
      directApprove: ctx.isAdmin && doc.status === 'in_review',
      // "Fix it" is said to the reviewer; an admin looking at another's document submits for them.
      submitHeading: ctx.isAdmin && !isMine(doc, ctx)
        ? doc.status === 'changes_requested'
          ? `Changes requested — submit again for ${firstName(doc.reviewer.name)}`
          : `Submit for ${firstName(doc.reviewer.name)}`
        : doc.status === 'changes_requested' ? 'Fix it, then submit again' : 'Your review',
    }
  }
  return base
}
