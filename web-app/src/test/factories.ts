import type { DocReview } from '../types'

/** A document's review with nothing said and nothing approved (tests build documents from it). */
export const emptyReview: DocReview = {
  comment: null, changesComment: null, approvedBy: null, approvedAt: null, approvalComment: null,
  docxSha256: null, carriedFrom: null, lastEvent: null,
}
