import { describe, expect, it } from 'vitest'
import { documentSubtitle } from '../docTree'

describe('documentSubtitle', () => {
  it("is the document's own process's title, as its cover prints it", () => {
    expect(documentSubtitle({ process: 'SWE.3', subtitle: 'Detailed Design' })).toBe('Software Detailed Design Specification')
    expect(documentSubtitle({ process: 'SWE.4', subtitle: 'Unit Test Specification' })).toBe('Software Unit Test Specification')
  })

  it("another process: the document's subtitle, else the process's name; never SWE.3's", () => {
    expect(documentSubtitle({ process: 'SWE.2', subtitle: 'Architecture' })).toBe('Architecture')
    expect(documentSubtitle({ process: 'SWE.2' })).toBe('Software Architecture Spec')
    expect(documentSubtitle({})).toBe('')
  })
})
