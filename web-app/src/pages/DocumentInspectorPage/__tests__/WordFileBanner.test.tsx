import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { WordFileBanner } from '../components/WordFileBanner'
import { componentNamer, readerBanner, updateBlocked } from '../../../lib/wordFiles'
import type { ExportReadiness, OutOfDateFile, VersionWriter } from '../../../types'

/* The reader's Word-file banner in each state (WORD_FILE_UPDATES W2; documents.html paintReady):
   out of date, updating with progress, done, failed + Try again, blocked by the writer, another
   update running, approved files kept — and how far a developer's update reaches. */

const BRAKE = 'Layer1.Brake-Controller'
const HVAC = 'Layer1.HVAC-Ctrl'
const SLIP = 'Layer1.Slip'
const docs = [
  { id: 'b3', group: BRAKE, name: 'Brake Controller', process: 'SWE.3', status: 'in_review' as const },
  { id: 'b4', group: BRAKE, name: 'Brake Controller', process: 'SWE.4', status: 'in_review' as const },
  { id: 'h3', group: HVAC, name: 'HVAC Ctrl', process: 'SWE.3', status: 'in_review' as const },
  { id: 's3', group: SLIP, name: 'Slip', process: 'SWE.3', status: 'in_review' as const },
  { id: 'h4', group: HVAC, name: 'HVAC Ctrl', process: 'SWE.4', status: 'approved' as const },
]
const f = (documentId: string, component: string, name: string, docType: string, over: Partial<OutOfDateFile> = {}): OutOfDateFile => ({
  documentId, component, name, docType, why: ['corrections'], corrections: 2, pictures: 0, layer: null, updating: false, ...over,
})
const OUT = [
  f('b3', BRAKE, 'Brake Controller', 'SWE.3'), f('b4', BRAKE, 'Brake Controller', 'SWE.4'),
  f('h3', HVAC, 'HVAC Ctrl', 'SWE.3', { why: ['layerAdded'], corrections: 0, layer: 'HAL_LAYER' }),
  f('s3', SLIP, 'Slip', 'SWE.3', { corrections: 1 }),
]
const r9 = (over: Partial<ExportReadiness> = {}): ExportReadiness => ({
  stale: true, explanation: null, overrideCount: 3, pendingRenders: 0, failedRenders: 0, reexport: null,
  outOfDate: OUT, approvedKept: [], writer: null, ...over,
})
const update = (components: string[], over: Partial<NonNullable<ExportReadiness['reexport']>> = {}) => ({
  jobId: 'job1', status: 'running', startedAt: null, completedAt: null, errorMessage: null, scope: 'out_of_date',
  reason: 'update', components, componentsDone: 0, startedBy: { userId: 'u1', name: 'Admin', initials: 'AD' }, ...over,
})
const generation: VersionWriter = {
  kind: 'generation', jobId: 'j5', command: 'generate', since: null, components: null, componentsDone: 11,
  componentsTotal: 54, startedBy: null,
}
const words = { versionTag: 'v1.2.0', nameOf: componentNamer(docs) }

function show(readiness: ExportReadiness | undefined, opts: {
  admin?: boolean; meId?: string; mine?: string[]; justUpdated?: string[]; failed?: boolean; doc?: number
} = {}) {
  const isAdmin = opts.admin ?? true
  const onAsk = vi.fn()
  const onDownload = vi.fn()
  const state = readerBanner({
    readiness, readinessFailed: opts.failed, doc: docs[opts.doc ?? 0], docs, isAdmin, meId: opts.meId ?? 'u1',
    myDocIds: opts.mine ?? [], justUpdated: opts.justUpdated ?? null, words,
  })
  render(
    <MemoryRouter>
      <WordFileBanner projectId="p1" state={state} isAdmin={isAdmin} rebuildBlocked={updateBlocked(readiness, null, words, true)}
        failedRenders={0} onAsk={onAsk} onDownload={onDownload} />
    </MemoryRouter>,
  )
  return { onAsk, onDownload, user: userEvent.setup(), banner: () => screen.getByRole('status', { name: 'Word file' }) }
}

describe('WordFileBanner', () => {
  it('out of date: this file and why, Update, and the rest an admin reaches with Update all', async () => {
    const { onAsk, user, banner } = show(r9())
    expect(banner()).toHaveTextContent('This Word file is out of date · 2 corrections not in it')
    expect(banner()).toHaveTextContent('2 more are out of date · Update all')
    expect(screen.getByRole('button', { name: /^Update$/ }).parentElement)
      .toHaveAttribute('title', 'Updates Brake Controller (SWE.3) and Brake Controller (SWE.4)')
    await user.click(screen.getByRole('button', { name: /^Update$/ }))
    expect(onAsk).toHaveBeenLastCalledWith({ components: [BRAKE] })
    await user.click(screen.getByRole('button', { name: 'Update all' }))
    expect(onAsk).toHaveBeenLastCalledWith({ components: null })
  })

  it("a developer reaches the documents they review: Update it, with only those components", async () => {
    const { onAsk, user, banner } = show(r9(), { admin: false, meId: 'u2', mine: ['s3'] })
    expect(banner()).toHaveTextContent('1 more you review · Update it')
    expect(screen.queryByRole('button', { name: 'More' })).toBeNull()      // Rebuild all is an admin's
    await user.click(screen.getByRole('button', { name: 'Update it' }))
    expect(onAsk).toHaveBeenLastCalledWith({ components: [SLIP] })
  })

  it('updating its component: the progress, per component', () => {
    const { banner } = show(r9({ reexport: update([BRAKE, HVAC], { componentsDone: 1 }) }))
    expect(banner()).toHaveTextContent('Updating Word files… 1 of 2')
    expect(screen.queryByRole('button', { name: /^Update$/ })).toBeNull()
  })

  it('done: Word files updated, with Download', async () => {
    const { onDownload, user, banner } = show(r9({ outOfDate: OUT.slice(2) }), { justUpdated: [BRAKE] })
    expect(banner()).toHaveTextContent('Word files updated. Download')
    await user.click(screen.getByRole('button', { name: 'Download' }))
    expect(onDownload).toHaveBeenCalled()
  })

  it('failed, to its starter: why, and Try again asks for the same update', async () => {
    const failed = r9({ reexport: update([BRAKE], { status: 'failed', errorMessage: 'flowchart pictures could not be drawn' }) })
    const { onAsk, user, banner } = show(failed)
    expect(banner()).toHaveTextContent('Update failed — Flowchart pictures could not be drawn.')
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onAsk).toHaveBeenLastCalledWith({ components: [BRAKE], rebuild: false })
  })

  it('blocked by the writer: the controls are off and one line says why', () => {
    const { banner } = show(r9({ writer: generation }))
    const btn = screen.getByRole('button', { name: /^Update$/ })
    expect(btn).toBeDisabled()
    expect(btn.parentElement).toHaveAttribute('title', 'Update after the generation of v1.2.0 ends.')
    expect(banner()).toHaveTextContent('Update after the generation of v1.2.0 ends.')
    expect(screen.queryByRole('button', { name: 'Update all' })).toBeNull()
  })

  it('another update running: after which one it can start', () => {
    const { banner } = show(r9({ reexport: update([SLIP]) }))
    expect(screen.getByRole('button', { name: /^Update$/ })).toBeDisabled()
    expect(banner()).toHaveTextContent('Update after the update of Slip ends.')
  })

  it("an admin's ⋯ Rebuild all, off with its reason while a generation runs", async () => {
    const { onAsk, user } = show(r9())
    await user.click(screen.getByRole('button', { name: 'More' }))
    await user.click(await screen.findByRole('menuitem', { name: /Rebuild all Word files…/ }))
    expect(onAsk).toHaveBeenLastCalledWith({ components: null, rebuild: true })
  })

  it('approved files kept: Approved, not changed', () => {
    const { banner } = show(r9({ outOfDate: [], approvedKept: [f('h4', HVAC, 'HVAC Ctrl', 'SWE.4')] }))
    expect(banner()).toHaveTextContent('Approved, not changed · HVAC Ctrl (SWE.4)')
  })

  it("R9 failed closed: can't tell — never up to date, no Update", () => {
    const { banner } = show(undefined, { failed: true })
    expect(banner()).toHaveTextContent('Can’t tell if this Word file is up to date.')
    expect(screen.queryByRole('button', { name: /Update/ })).toBeNull()
  })

  it("2: a developer's failed update of a component beyond their reach from here: Open it to try again", () => {
    // u2 reviews Slip; updated HVAC Ctrl from its SWE.3; looks at Brake Controller's — no Try again here.
    const failed = r9({ reexport: update([HVAC], { status: 'failed', errorMessage: 'pictures could not be drawn',
      startedBy: { userId: 'u2', name: 'Dev', initials: 'D' } }) })
    const { banner } = show(failed, { admin: false, meId: 'u2', mine: ['s3'], doc: 2 })
    // On HVAC Ctrl's own document it is in reach: Try again.
    expect(banner()).toHaveTextContent('Update failed — Pictures could not be drawn.')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('partly failed: its failed component says so; its written one says updated', () => {
    const partial = r9({ outOfDate: OUT.filter((x) => x.component === HVAC), reexport: update([BRAKE, HVAC], {
      status: 'complete', componentsFailed: [HVAC], errorMessage: 'a download held the file' }) })
    show(partial, { doc: 2 })
    expect(screen.getByRole('status', { name: 'Word file' })).toHaveTextContent('Update failed — A download held the file.')
  })
})

describe('WordFileBanner — Try again from where the server would refuse it (finding 2)', () => {
  it('a component beyond reach from this document: no Try again, but the document that reaches it, linked', () => {
    // u2 reviews Slip, and updated HVAC Ctrl and Slip from HVAC Ctrl's SWE.3; both failed. On Slip's
    // document, HVAC Ctrl is out of reach (403 NOT_YOUR_DOCUMENTS): open its document instead.
    const failed = r9({ reexport: update([HVAC, SLIP], { status: 'failed', errorMessage: 'pictures could not be drawn',
      startedBy: { userId: 'u2', name: 'Dev', initials: 'D' } }) })
    const { banner } = show(failed, { admin: false, meId: 'u2', mine: ['s3'], doc: 3 })
    expect(banner()).toHaveTextContent('Update failed — Pictures could not be drawn.')
    expect(banner()).toHaveTextContent('Open HVAC Ctrl (SWE.3) to try again.')
    expect(screen.getByRole('link', { name: 'HVAC Ctrl (SWE.3)' })).toHaveAttribute('href', '/projects/p1/documents/h3')
    expect(screen.queryByRole('button', { name: 'Try again' })).toBeNull()
  })
})
