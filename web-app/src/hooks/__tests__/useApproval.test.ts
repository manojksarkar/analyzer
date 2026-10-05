import { describe, expect, it } from 'vitest'
import { approvalErrorMessage } from '../useApproval'
import { saveErrorMessage } from '../useReview'
import { ApiError } from '../../lib/http'

describe('approvalErrorMessage', () => {
  it('says each 409 code of the review routes in words', () => {
    expect(approvalErrorMessage(new ApiError('x', 409, 'WRONG_STATE'))).toMatch(/state changed/)
    expect(approvalErrorMessage(new ApiError('x', 409, 'DOCUMENT_APPROVED'))).toMatch(/approved, so it is locked/)
    expect(approvalErrorMessage(new ApiError('x', 409, 'HAS_REVIEWER'))).toBe('Someone already reviews it.')
    expect(approvalErrorMessage(new ApiError('x', 409, 'NO_REVIEWER'))).toBe('It needs a reviewer first.')
    expect(approvalErrorMessage(new ApiError('x', 422, 'NOT_A_MEMBER'))).toMatch(/not an active member/)
  })
  it("keeps STALE_EXPORT's reason", () => {
    expect(approvalErrorMessage(new ApiError('3 corrections are not in it.', 409, 'STALE_EXPORT')))
      .toBe('Its Word file does not have every correction yet: re-export first, then approve. 3 corrections are not in it.')
  })
  it("falls back to the server's message", () => {
    expect(approvalErrorMessage(new ApiError('Comment is too long', 422))).toBe('Comment is too long')
    expect(approvalErrorMessage(new ApiError('Forbidden', 403))).toBe('You cannot do this on this document.')
  })
})

describe('saveErrorMessage (a correction on an approved document)', () => {
  it('says the document is locked', () => {
    expect(saveErrorMessage(new ApiError('x', 409, 'DOCUMENT_APPROVED'))).toMatch(/approved, so it is locked/)
    // A 409 with no code (no stored graph, nothing to undo, …) says what the server said; only
    // VERSION_REGENERATING means a run (hooks/__tests__/useReview.test.ts).
    expect(saveErrorMessage(new ApiError('the flowchart has no stored graph', 409))).toBe('the flowchart has no stored graph')
  })
})
