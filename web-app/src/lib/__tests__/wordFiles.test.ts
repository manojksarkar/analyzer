import { describe, expect, it } from 'vitest'
import {
  compNames, componentNamer, editHold, failureFor, isUpdating, outOfDateFiles, outOfDateWhy, ownOutOfDate,
  readerBanner, readinessPollMs, reasonsOf, refusalSentence, retryOf, runningUpdate, submitBlockedSentence,
  updateBlocked, visibleFailure, wordFilesRow, writtenComponents,
} from '../wordFiles'
import type { ExportReadiness, OutOfDateFile, VersionWriter } from '../../types'

/* Word file updates: the rules every screen shares, in the mockup's words
   (docs/design/WORD_FILE_UPDATES.md; docs/ui-mockups/documents.html). */

const BRAKE = 'Layer1.Brake-Controller'
const HVAC = 'Layer1.HVAC-Ctrl'
const SLIP = 'Layer1.Slip'

const file = (documentId: string, component: string, name: string, docType: string,
  over: Partial<OutOfDateFile> = {}): OutOfDateFile => ({
  documentId, component, name, docType, why: ['corrections'], corrections: 2, pictures: 0, layer: null,
  updating: false, ...over,
})

const brake3 = file('b3', BRAKE, 'Brake Controller', 'SWE.3')
const brake4 = file('b4', BRAKE, 'Brake Controller', 'SWE.4')
const hvac3 = file('h3', HVAC, 'HVAC Ctrl', 'SWE.3', { why: ['layerAdded'], corrections: 0, layer: 'HAL_LAYER' })
const slip3 = file('s3', SLIP, 'Slip', 'SWE.3', { corrections: 1 })

const docs = [
  { id: 'b3', group: BRAKE, name: 'Brake Controller', process: 'SWE.3', status: 'in_review' as const },
  { id: 'b4', group: BRAKE, name: 'Brake Controller', process: 'SWE.4', status: 'in_review' as const },
  { id: 'h3', group: HVAC, name: 'HVAC Ctrl', process: 'SWE.3', status: 'in_review' as const },
  { id: 's3', group: SLIP, name: 'Slip', process: 'SWE.3', status: 'in_review' as const },
  { id: 'h4', group: HVAC, name: 'HVAC Ctrl', process: 'SWE.4', status: 'approved' as const },
]

const r9 = (over: Partial<ExportReadiness> = {}): ExportReadiness => ({
  stale: true, explanation: null, overrideCount: 3, pendingRenders: 0, failedRenders: 0, reexport: null,
  outOfDate: [brake3, brake4, hvac3, slip3], approvedKept: [], writer: null, ...over,
})

const words = { versionTag: 'v1.2.0', nameOf: componentNamer(docs) }

const generation: VersionWriter = {
  kind: 'generation', jobId: 'job5e21aa0c', command: 'generate', since: null, components: null,
  componentsDone: 11, componentsTotal: 54, startedBy: null,
}

const running = (components: string[], over: Partial<NonNullable<ExportReadiness['reexport']>> = {}) => ({
  jobId: 'job3c9e1f20', status: 'running', startedAt: null, completedAt: null, errorMessage: null,
  scope: 'out_of_date', reason: 'update', components, componentsDone: 0,
  startedBy: { userId: 'u2', name: 'Developer B', initials: 'DB' }, ...over,
})

describe('why a Word file is out of date', () => {
  it('says the reasons short: corrections, a layer added since, or both; brief in the Review tab', () => {
    expect(outOfDateWhy(brake3)).toBe('2 corrections not in it')
    expect(outOfDateWhy(brake3, true)).toBe('2 corrections')
    expect(outOfDateWhy(hvac3)).toBe('HAL_LAYER added since')
    expect(outOfDateWhy({ ...hvac3, why: ['corrections', 'layerAdded'], corrections: 1 }))
      .toBe('1 correction not in it, HAL_LAYER added since')
    expect(outOfDateWhy({ ...brake3, why: ['pictures'], pictures: 1 })).toBe('1 picture being drawn')
  })
  it('counts the version-wide reasons once per component (its SWE.3 and SWE.4 print the same corrections)', () => {
    expect(reasonsOf([brake3, brake4, hvac3, slip3])).toBe('3 corrections, HAL_LAYER added since')
  })
  it('names components short', () => {
    expect(compNames(['Brake Controller'])).toBe('Brake Controller')
    expect(compNames(['Brake Controller', 'HVAC Ctrl'])).toBe('Brake Controller and HVAC Ctrl')
    expect(compNames(['A', 'B', 'C'])).toBe('3 components')
    expect(compNames(['A', 'B', 'C'], true)).toBe('these 3 components')
    expect(componentNamer([])('Layer1.Sample-Core')).toBe('Sample-Core')
  })
  it('an older API (no outOfDate): every not-approved document of a stale component', () => {
    const old: ExportReadiness = { stale: true, staleComponents: [HVAC], explanation: null, overrideCount: 1,
      pendingRenders: 0, failedRenders: 0, reexport: null }
    expect(outOfDateFiles(old, docs).map((f) => f.documentId)).toEqual(['h3'])
  })
})

describe('when nothing can start (one update per version, none while a run holds it)', () => {
  it('a generation holds the version', () => {
    expect(updateBlocked(r9({ writer: generation }), [BRAKE], words)).toBe('Update after the generation of v1.2.0 ends.')
    expect(updateBlocked(r9({ writer: generation }), null, words, true)).toBe('Rebuild after the generation of v1.2.0 ends.')
  })
  it('another update runs: already updating when it covers the ask, else after it ends', () => {
    const r = r9({ reexport: running([BRAKE]) })
    expect(updateBlocked(r, [BRAKE], words)).toBe('Brake Controller is already updating.')
    expect(updateBlocked(r, [HVAC], words)).toBe('Update after the update of Brake Controller ends.')
    expect(updateBlocked(r, null, words, true)).toBe('Rebuild after the update of Brake Controller ends.')
    expect(updateBlocked(r9({ reexport: running([BRAKE, HVAC], { scope: 'all' }) }), [SLIP], words))
      .toBe('Update after the rebuild of v1.2.0 ends.')
  })
  it('nothing holds it: it can start', () => {
    expect(updateBlocked(r9(), [BRAKE], words)).toBe('')
    expect(updateBlocked(r9({ reexport: running([BRAKE], { status: 'complete' }) }), [BRAKE], words)).toBe('')
  })
  it('a refusal says the same (409 REEXPORT_RUNNING / VERSION_BUSY)', () => {
    expect(refusalSentence({ code: 'REEXPORT_RUNNING', scope: 'out_of_date', components: [HVAC], writer: null }, words))
      .toBe('Update after the update of HVAC Ctrl ends.')
    expect(refusalSentence({ code: 'REEXPORT_RUNNING', scope: 'export', components: [HVAC], writer: null }, words))
      .toBe('Update after the generation of v1.2.0 ends.')
    expect(refusalSentence({ code: 'VERSION_BUSY', scope: null, components: [], writer: generation }, words))
      .toBe('Update after the generation of v1.2.0 ends.')
  })
  it("Submit's toast when the update could not start", () => {
    expect(submitBlockedSentence(generation, words)).toBe('Update its Word file after the generation ends.')
    expect(submitBlockedSentence({ ...generation, kind: 'update', components: [HVAC] }, words))
      .toBe('Update its Word file after the update of HVAC Ctrl ends.')
  })
})

describe('updating, and the edit hold', () => {
  it('a document of a component being written is updating; an approved one never is', () => {
    const r = r9({ reexport: running([HVAC]) })
    expect(isUpdating(r, docs[2])).toBe(true)
    expect(isUpdating(r, docs[0])).toBe(false)
    expect(isUpdating(r, docs[4])).toBe(false)
    expect(isUpdating(r9({ outOfDate: [{ ...brake3, updating: true }] }), docs[0])).toBe(true)
  })
  it("corrections wait in the components being updated only; a rebuild holds every one; a generation's export too", () => {
    expect(editHold(r9({ reexport: running([BRAKE]) }), docs[0])).toBe('update')
    expect(editHold(r9({ reexport: running([BRAKE]) }), docs[2])).toBeNull()
    expect(editHold(r9({ reexport: running([BRAKE, HVAC, SLIP], { scope: 'all' }) }), docs[3])).toBe('rebuild')
    expect(editHold(r9({ writer: { ...generation, kind: 'export', components: [SLIP] } }), docs[3])).toBe('update')
    // A generation holds the version but not editing (the server answers a save in it).
    expect(editHold(r9({ writer: generation }), docs[0])).toBeNull()
  })
})

describe('a failed update', () => {
  const failed = r9({ reexport: running([BRAKE], { status: 'failed', errorMessage: 'flowchart pictures could not be drawn' }) })
  it('is shown to its starter, with why; to anyone else the files are simply out of date', () => {
    expect(visibleFailure(failed, 'u2')?.why).toBe('Flowchart pictures could not be drawn.')
    expect(visibleFailure(failed, 'u9')).toBeNull()
    expect(failureFor(failed, 'u2', docs[0], true)).not.toBeNull()
    expect(failureFor(failed, 'u2', docs[2], true)).toBeNull()
  })
})

describe('the reader banner', () => {
  const base = { docs, isAdmin: true, meId: 'u1', myDocIds: [] as string[], justUpdated: null, words }

  it('out of date: this file and why, and the rest an admin reaches (Update all)', () => {
    const b = readerBanner({ ...base, readiness: r9(), doc: docs[0] })
    expect(b.kind).toBe('outOfDate')
    if (b.kind !== 'outOfDate') return
    expect(b.why).toBe('2 corrections not in it')
    expect(b.mine.map((f) => f.documentId)).toEqual(['b3', 'b4'])
    expect(b.others.map((f) => f.documentId)).toEqual(['h3', 's3'])
    expect(b.blockedMine).toBe('')
  })

  it("a developer's reach: the components of the documents they review, plus the one open", () => {
    const dev = { ...base, isAdmin: false, meId: 'u2', myDocIds: ['s3'] }
    const b = readerBanner({ ...dev, readiness: r9(), doc: docs[0] })
    if (b.kind !== 'outOfDate') throw new Error(b.kind)
    expect(b.mine.map((f) => f.documentId)).toEqual(['b3', 'b4'])
    expect(b.others.map((f) => f.documentId)).toEqual(['s3'])
    // Kept approved files: only the ones they review.
    const kept = file('h4', HVAC, 'HVAC Ctrl', 'SWE.4')
    const k = readerBanner({ ...dev, readiness: r9({ approvedKept: [kept] }), doc: docs[0] })
    expect(k.kind === 'outOfDate' && k.kept).toEqual([])
    const a = readerBanner({ ...base, readiness: r9({ approvedKept: [kept] }), doc: docs[0] })
    expect(a.kind === 'outOfDate' && a.kept.map((f) => f.documentId)).toEqual(['h4'])
  })

  it('updating its component: the progress, per component', () => {
    const b = readerBanner({ ...base, readiness: r9({ reexport: running([BRAKE, HVAC], { componentsDone: 1 }) }), doc: docs[0] })
    expect(b).toEqual({ kind: 'updating', title: 'Updating Word files…', count: '1 of 2' })
  })

  it('just written: Word files updated', () => {
    const r = r9({ outOfDate: [hvac3, slip3] })
    expect(readerBanner({ ...base, readiness: r, doc: docs[0], justUpdated: [BRAKE] }).kind).toBe('updated')
  })

  it('failed, to its starter: why, and Try again — off while a generation holds the version', () => {
    const failed = r9({ reexport: running([BRAKE], { status: 'failed', errorMessage: 'flowchart pictures could not be drawn' }) })
    const b = readerBanner({ ...base, meId: 'u2', readiness: failed, doc: docs[0] })
    expect(b).toMatchObject({ kind: 'failed', blocked: '', failure: { why: 'Flowchart pictures could not be drawn.' } })
    const held = readerBanner({ ...base, meId: 'u2', readiness: { ...failed, writer: generation }, doc: docs[0] })
    expect(held).toMatchObject({ kind: 'failed', blocked: 'Update after the generation of v1.2.0 ends.' })
    // Anyone else: simply out of date.
    expect(readerBanner({ ...base, meId: 'u9', readiness: failed, doc: docs[0] }).kind).toBe('outOfDate')
  })

  it('blocked by the writer, or by another update: each control says why', () => {
    const g = readerBanner({ ...base, readiness: r9({ writer: generation }), doc: docs[0] })
    expect(g).toMatchObject({ blockedMine: 'Update after the generation of v1.2.0 ends.' })
    const u = readerBanner({ ...base, readiness: r9({ reexport: running([SLIP]) }), doc: docs[0] })
    expect(u).toMatchObject({ blockedMine: 'Update after the update of Slip ends.' })
    // The one updating is not offered again.
    expect(u.kind === 'outOfDate' && u.others.map((f) => f.documentId)).toEqual(['h3'])
  })

  it('only approved files kept, or nothing to say', () => {
    const kept = file('h4', HVAC, 'HVAC Ctrl', 'SWE.4')
    expect(readerBanner({ ...base, readiness: r9({ outOfDate: [], approvedKept: [kept] }), doc: docs[0] }).kind).toBe('kept')
    expect(readerBanner({ ...base, readiness: r9({ stale: false, outOfDate: [] }), doc: docs[0] }).kind).toBe('none')
  })
})

/* The review's findings (numbered as in the review) and the server's changes of the same day. */
describe('review findings', () => {
  const base = { docs, isAdmin: true, meId: 'u1', myDocIds: [] as string[], justUpdated: null, words }

  it('1: a resume holds the components it writes, as an export does', () => {
    const resume: VersionWriter = { ...generation, kind: 'resume', components: [SLIP] }
    expect(editHold(r9({ writer: resume }), docs[3])).toBe('update')
    expect(editHold(r9({ writer: resume }), docs[0])).toBeNull()
  })

  it("2: Try again only within a developer's reach; elsewhere, the document that reaches it", () => {
    // Developer u2 reviews Slip; they updated HVAC Ctrl from its SWE.3, and it failed.
    const failed = r9({ reexport: running([HVAC], { status: 'failed', errorMessage: 'pictures could not be drawn',
      startedBy: { userId: 'u2', name: 'Dev', initials: 'D' } }) })
    const dev = { ...base, isAdmin: false, meId: 'u2', myDocIds: ['s3'] }
    // From HVAC Ctrl's own document: here.
    expect(readerBanner({ ...dev, readiness: failed, doc: docs[2] })).toMatchObject({ kind: 'failed', retry: { kind: 'here' } })
    // From the Documents page (no document open): open it.
    expect(wordFilesRow({ ...dev, readiness: failed })).toMatchObject({
      kind: 'failed', retry: { kind: 'open', docId: 'h3', label: 'HVAC Ctrl (SWE.3)' },
    })
    // An admin reaches every component.
    const byAdmin = r9({ reexport: { ...failed.reexport!, startedBy: { userId: 'u1', name: 'A', initials: 'A' } } })
    expect(wordFilesRow({ ...base, readiness: byAdmin })).toMatchObject({ kind: 'failed', retry: { kind: 'here' } })
    // Within the documents they review: here.
    const f = visibleFailure(failed, 'u2')!
    expect(retryOf({ ...f, components: [SLIP] }, { isAdmin: false, reviewed: [SLIP], docs })).toEqual({ kind: 'here' })
  })

  it('3: an older server — an update without scope or components — holds every document', () => {
    const old = r9({ reexport: { jobId: 'j1', status: 'running', startedAt: null, completedAt: null, errorMessage: null } })
    expect(runningUpdate(old)).toMatchObject({ rebuild: true, components: [] })
    expect(editHold(old, docs[0])).toBe('rebuild')
    expect(isUpdating(old, docs[3])).toBe(true)
  })

  it('5: the failure shows only on a document it was to write, still out of date — never elsewhere', () => {
    const failed = r9({ outOfDate: [hvac3], reexport: running([HVAC], { status: 'failed', errorMessage: 'x',
      startedBy: { userId: 'u1', name: 'A', initials: 'A' } }) })
    expect(readerBanner({ ...base, readiness: failed, doc: docs[2] }).kind).toBe('failed')
    // Brake Controller is up to date here: no "Update failed" on it.
    expect(readerBanner({ ...base, readiness: failed, doc: docs[0] }).kind).toBe('outOfDate')
    // An approved document: never.
    expect(readerBanner({ ...base, readiness: failed, doc: docs[4] }).kind).not.toBe('failed')
  })

  it('6: an approved document never says "Word files updated"', () => {
    const r = r9({ outOfDate: [] })
    expect(readerBanner({ ...base, readiness: r, doc: docs[4], justUpdated: [HVAC] }).kind).not.toBe('updated')
    expect(readerBanner({ ...base, readiness: r, doc: docs[2], justUpdated: [HVAC] }).kind).toBe('updated')
  })

  it('7: every 2.5 s only for an update or a rebuild; an export or a resume (days long) every 15 s', () => {
    expect(readinessPollMs(r9({ reexport: running([BRAKE]) }))).toBe(2500)
    expect(readinessPollMs(r9({ writer: { ...generation, kind: 'export', components: [SLIP] } }))).toBe(15_000)
    expect(readinessPollMs(r9({ writer: { ...generation, kind: 'resume', components: [SLIP] } }))).toBe(15_000)
    expect(readinessPollMs(r9({ outOfDate: [{ ...slip3, updating: true }] }))).toBe(15_000)
    expect(readinessPollMs(r9())).toBe(false)
  })

  it("8: an older server's A15 — stale, staleComponents [] — is this document's, never up to date", () => {
    const a15: ExportReadiness = { stale: true, staleComponents: [], explanation: null, overrideCount: 1,
      pendingRenders: 0, failedRenders: 0, reexport: null }
    expect(ownOutOfDate(a15, docs[0])).toMatchObject({ documentId: 'b3', component: BRAKE })
    expect(ownOutOfDate({ ...a15, stale: false }, docs[0])).toBeUndefined()
    expect(ownOutOfDate(a15, docs[4])).toBeUndefined()      // approved: its kept file
  })

  it('11: a command-line update or rebuild holding the version is named for what it is', () => {
    const cliUpdate: VersionWriter = { ...generation, kind: 'update', components: [HVAC] }
    expect(refusalSentence({ code: 'VERSION_BUSY', scope: null, components: [], writer: cliUpdate }, words))
      .toBe('Update after the update of HVAC Ctrl ends.')
    expect(refusalSentence({ code: 'VERSION_BUSY', scope: null, components: [], writer: { ...cliUpdate, kind: 'rebuild' } }, words))
      .toBe('Update after the rebuild of v1.2.0 ends.')
  })
})

describe("the server's changes: a partly failed update, REEXPORT_RUNNING's kind, failing closed", () => {
  const base = { docs, isAdmin: true, meId: 'u1', myDocIds: [] as string[], justUpdated: null, words }
  const mine = { userId: 'u1', name: 'A', initials: 'A' }

  it('partly failed (complete, componentsFailed): Update failed for those only, Word files updated for the rest', () => {
    const r = r9({ outOfDate: [hvac3], reexport: running([BRAKE, HVAC], {
      status: 'complete', componentsFailed: [HVAC], errorMessage: 'a download held the file', startedBy: mine,
    }) })
    expect(visibleFailure(r, 'u1')).toMatchObject({ components: [HVAC], partial: true, rebuild: false,
      why: 'A download held the file.' })
    expect(writtenComponents(r.reexport!)).toEqual([BRAKE])
    expect(readerBanner({ ...base, readiness: r, doc: docs[2] })).toMatchObject({ kind: 'failed', retry: { kind: 'here' } })
    expect(readerBanner({ ...base, readiness: r, doc: docs[0], justUpdated: [BRAKE] }).kind).toBe('updated')
    expect(wordFilesRow({ ...base, readiness: r })).toMatchObject({ kind: 'failed', failure: { components: [HVAC] } })
  })

  it('all failed (failed, componentsFailed every one): Update failed for every one', () => {
    const r = r9({ reexport: running([BRAKE, HVAC], { status: 'failed', componentsFailed: [BRAKE, HVAC],
      errorMessage: 'Update failed: pictures', startedBy: mine }) })
    expect(visibleFailure(r, 'u1')).toMatchObject({ components: [BRAKE, HVAC], partial: false })
    expect(failureFor(r, 'u1', docs[0], true)).not.toBeNull()
  })

  it('REEXPORT_RUNNING names a running resume or export as the generation, by its kind', () => {
    const resume = { code: 'REEXPORT_RUNNING', kind: 'resume', scope: 'export', components: [SLIP], writer: null }
    expect(refusalSentence(resume, words)).toBe('Update after the generation of v1.2.0 ends.')
    expect(refusalSentence({ ...resume, kind: 'rebuild', scope: 'all' }, words)).toBe('Update after the rebuild of v1.2.0 ends.')
    expect(refusalSentence({ ...resume, kind: 'update', scope: 'out_of_date', components: [HVAC] }, words))
      .toBe('Update after the update of HVAC Ctrl ends.')
  })

  it('R9 failing closed: cannot tell, never up to date; Submit says the server words', () => {
    expect(readerBanner({ ...base, readiness: undefined, readinessFailed: true, doc: docs[0] }).kind).toBe('unknown')
    expect(wordFilesRow({ ...base, readiness: undefined, readinessFailed: true }).kind).toBe('unknown')
    expect(readerBanner({ ...base, readiness: undefined, doc: docs[0] }).kind).toBe('none')      // still loading
    expect(submitBlockedSentence({ ...generation, kind: 'other', message: 'Could not read which Word files are out of date.' }, words))
      .toBe('Could not read which Word files are out of date.')
  })
})
