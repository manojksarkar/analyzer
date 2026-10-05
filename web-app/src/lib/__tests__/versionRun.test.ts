import { describe, expect, it } from 'vitest'
import { describeVersionRun } from '../versionRun'

/* How a version was made, in one line for its card (GET /versions `run`). */

describe('describeVersionRun', () => {
  it('a web run of named components, both documents', () => {
    expect(describeVersionRun({
      madeBy: 'web', docType: 'all', modelOnly: false,
      scope: { type: 'component', names: ['L1.A', 'L1.B', 'L1.C', 'L1.D', 'L1.E', 'L1.F', 'L1.G'] },
    })).toBe('Web run · 7 components · SWE.3 + SWE.4')
  })
  it('a command-line run of one layer, model only', () => {
    expect(describeVersionRun({ madeBy: 'cli', scope: { type: 'layer', names: ['Layer1'] }, docType: 'swe3', modelOnly: true }))
      .toBe('Command line · layer Layer1 · model only')
  })
  it('the whole project; two groups by name; one document type', () => {
    expect(describeVersionRun({ madeBy: 'cli', scope: { type: 'project', names: [] }, docType: 'swe4', modelOnly: false }))
      .toBe('Command line · whole project · SWE.4')
    expect(describeVersionRun({ madeBy: null, scope: { type: 'group', names: ['G1', 'G2'] }, docType: null, modelOnly: false }))
      .toBe('groups G1, G2')
  })
  it('nothing to say: no line', () => {
    expect(describeVersionRun(null)).toBeNull()
    expect(describeVersionRun({ madeBy: null, scope: null, docType: null, modelOnly: false })).toBeNull()
  })
})
