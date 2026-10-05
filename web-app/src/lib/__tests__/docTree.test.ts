import { describe, expect, it } from 'vitest'
import { documentSubtitle, shownProcesses } from '../docTree'

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

/* #37: a process nothing generates was a tab and a row of its own, always empty. */
describe('shownProcesses', () => {
  it('offers the processes the app makes, in order, and any other only with a document', () => {
    expect(shownProcesses([])).toEqual(['SWE.3', 'SWE.4'])
    expect(shownProcesses([{ process: 'SWE.3' }])).toEqual(['SWE.3', 'SWE.4'])
    expect(shownProcesses([{ process: 'SWE.4' }, { process: 'SYS.2' }])).toEqual(['SYS.2', 'SWE.3', 'SWE.4'])
  })
})
