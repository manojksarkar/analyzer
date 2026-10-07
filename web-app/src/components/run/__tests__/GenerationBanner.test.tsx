import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { GenerationBanner } from '../GenerationBanner'

/* Staged generation in one row (GET …/versions/{vid}/components): shown only while something is
   missing, at work or stopped; "View components" opens the drawer; an admin stops a web job. A
   second row says which Word files are out of date, and offers the update this role may start. */

type Doc = { id: string; process: string; status: string }
const comp = (component: string, state: string, documents: Doc[] = [], over: Record<string, unknown> = {}) => ({
  component, layer: component.split('.')[0], name: component.split('.')[1], state, in_model: true,
  layer_parsed: true, group: null,
  error: state === 'failed' ? 'Components: L1.Util: stopped with exit code 1' : null, documents, ...over,
})
const DOC = (id: string, status = 'in_review') => ({ id, process: 'SWE.3', status })

const ALL_DONE = {
  version_id: 'ver1',
  components: [comp('Layer1.Math', 'generated', [DOC('d1')]), comp('Layer1.App', 'generated', [DOC('d2')])],
  counts: { generated: 2 }, run: null, job: null,
}

/** Nothing at work, two of four without documents. */
const IDLE = {
  version_id: 'ver1',
  components: [comp('Layer1.Math', 'generated', [DOC('d1')]), comp('Layer1.App', 'generated', [DOC('d2')]),
    comp('Layer1.Util', 'not_requested'), comp('Layer2.Gpio', 'not_requested')],
  counts: { generated: 2, not_requested: 2 }, run: null, job: null,
}

const STOPPED = {
  ...IDLE,
  run: {
    command: 'generate', alive: false, stopped: true, outcome: 'running', host: 'box',
    started_at: '2026-10-01T09:00:00Z', finished_at: null, stage: 'LLM-description-pass1',
    done: 10, total: 40, stage_started_at: '2026-10-01T09:00:00Z', progress_at: new Date(Date.now() - 3 * 3600e3).toISOString(),
  },
}

const RUNNING = (mode: string) => ({
  ...STOPPED,
  run: { ...STOPPED.run, command: 'export', alive: true, stopped: false, stage: 'flowcharts', done: 38, total: 112,
    started_at: new Date(Date.now() - 2 * 3600e3).toISOString() },
  job: { id: 'job9', mode, status: 'running' },
})

/** Layer2 added to a version that had Layer1: Math's documents are out of date. */
const ADDED = {
  version_id: 'ver1',
  components: [comp('Layer1.Math', 'stale', [DOC('d1')]), comp('Layer1.App', 'generated', [DOC('d2')])],
  counts: { generated: 1, stale: 1 }, run: null, job: null,
}

/** R9 (WORD_FILE_UPDATES §4.2): `outOfDate` lists the Word files that are out of date. */
const r9 = (stale: boolean, staleComponents?: string[], over: object = {}) => ({
  stale, reason: '', explanation: '', overrideCount: stale ? 1 : 0, pendingRenders: 0, failedRenders: 0,
  newestOverrideAt: null, oldestDerivationAt: null, reexport: null,
  ...(staleComponents ? { staleComponents } : {}), ...over,
})
const outOfDate = (documentId: string, component: string, over: object = {}) => ({
  documentId, component, name: component.split('.')[1], docType: 'SWE.3', why: ['corrections'], corrections: 2,
  pictures: 0, layer: null, updating: false, ...over,
})
/** Math's documents out of date because Layer2 was added; App's for 2 corrections. */
const BEHIND = r9(true, ['Layer1.App', 'Layer1.Math'], {
  outOfDate: [
    outOfDate('d2', 'Layer1.App'),
    outOfDate('d1', 'Layer1.Math', { why: ['layerAdded'], corrections: 0, layer: 'Layer2' }),
  ],
  approvedKept: [], writer: null,
})
/** The version's documents (who reviews which). */
const DOCS = [
  { id: 'd1', name: 'Math', process: 'SWE.3', layer: 'Layer1', group: 'Layer1.Math', status: 'in_review', version_id: 'ver1',
    updated_at: '2026-10-01T09:00:00Z', reviewer: { user_id: 'u7', name: 'Dev Seven', initials: 'DS' }, review: null },
  { id: 'd2', name: 'App', process: 'SWE.3', layer: 'Layer1', group: 'Layer1.App', status: 'in_review', version_id: 'ver1',
    updated_at: '2026-10-01T09:00:00Z', reviewer: { user_id: 'u2', name: 'Dev Two', initials: 'DT' }, review: null },
]

function setup(isAdmin: boolean, body: object, opts: {
  readiness?: object | 'pending' | 'failed'; compact?: boolean; needsModel?: boolean; url?: string
} = {}) {
  const { readiness = r9(false, []), compact, needsModel, url = '/' } = opts
  const cancelled: string[] = []
  const reexported: string[] = []
  const resumed: string[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/versions/ver1/components`, () => HttpResponse.json(body)),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver1/export-readiness`, async () => {
      if (readiness === 'pending') await new Promise(() => {})
      if (readiness === 'failed') return HttpResponse.json({ detail: { message: 'Database unavailable' } }, { status: 500 })
      return HttpResponse.json(readiness)
    }),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: DOCS, pagination: { page: 1, per_page: 100, total: DOCS.length } })),
    http.post(`${API_BASE_URL}/projects/p1/versions/ver1/reexport`, async ({ request }) => {
      reexported.push(JSON.stringify(await request.json()))
      return HttpResponse.json({ job_id: 'jobrx', status: 'queued', version_id: 'ver1', scope: 'out_of_date', components: [], joined: false }, { status: 202 })
    }),
    http.post(`${API_BASE_URL}/projects/p1/versions/ver1/resume`, () => {
      resumed.push('ver1')
      return HttpResponse.json({ job_id: 'jobres', status: 'queued', version_id: 'ver1' }, { status: 202 })
    }),
    http.post(`${API_BASE_URL}/projects/p1/jobs/:jobId/cancel`, ({ params }) => {
      cancelled.push(String(params.jobId))
      return HttpResponse.json({ job: null })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrap = (c: ReactNode) => (
    <MemoryRouter initialEntries={[url]}><QueryClientProvider client={client}>{c}</QueryClientProvider></MemoryRouter>
  )
  const view = render(wrap(
    <GenerationBanner projectId="p1" versionId="ver1" versionTag="v1.2.0" isAdmin={isAdmin} compact={compact} needsModel={needsModel} />,
  ))
  return { cancelled, reexported, resumed, user: userEvent.setup(), ...view }
}

const banner = () => screen.findByRole('status', { name: 'Generation' })

describe('GenerationBanner', () => {
  it('renders nothing once every component has its documents and nothing runs', async () => {
    const { container } = setup(true, ALL_DONE)
    await new Promise((r) => setTimeout(r, 100))
    expect(container).toBeEmptyDOMElement()
  })

  it('idle, some without documents: says how many, and how far the version has got', async () => {
    setup(false, IDLE)
    const row = await banner()
    expect(row).toHaveTextContent('2 components have no documents yet · 2 of 4 done')
    expect(within(row).getByRole('button', { name: 'View components' })).toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('a run at work: its verb, progress, stage and start; an admin stops the web job, after asking', async () => {
    const { cancelled, user } = setup(true, RUNNING('export'))
    const row = await banner()
    expect(row).toHaveTextContent('Generating documents · 2 of 4 components done · drawing flowcharts, 38 of 112 · started 2h ago')
    await user.click(within(row).getByRole('button', { name: 'Stop' }))
    const dialog = await screen.findByRole('dialog', { name: 'Stop making these documents?' })
    expect(within(dialog).getByText(/Components already finished keep their documents/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(cancelled).toEqual(['job9']))
  })

  it("stopping the version's own run says the version goes with it", async () => {
    const { cancelled, user } = setup(true, RUNNING('auto'))
    await user.click(within(await banner()).getByRole('button', { name: 'Stop' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel this generation?' })
    expect(within(dialog).getByText(/this version is removed/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Keep running' }))
    expect(cancelled).toEqual([])
  })

  it('a developer sees the run, but no Stop', async () => {
    setup(false, RUNNING('export'))
    expect(await banner()).toHaveTextContent('Generating documents')
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('no Stop for an admin when the run is a command-line one (no web job)', async () => {
    setup(true, { ...RUNNING('export'), job: null })
    expect(await banner()).toHaveTextContent('Generating documents')
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('the Documents page keeps it short: no stage, no start time, no Stop', async () => {
    setup(true, RUNNING('export'), { compact: true })
    const row = await banner()
    expect(row).toHaveTextContent('Generating documents · 2 of 4 components done')
    expect(row).not.toHaveTextContent(/flowcharts|started/)
    expect(within(row).queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('an update at work is named for what it does', async () => {
    setup(false, { ...RUNNING('reexport'), run: { ...RUNNING('reexport').run, command: 'reexport', stage: 'docx_exporter', done: 3, total: 25 } })
    expect(await banner()).toHaveTextContent('Updating Word files · 2 of 4 components done · writing Word files, 3 of 25')
  })

  it('a run cut short: says so; an admin resumes it from here, the command one click away', async () => {
    const { resumed, user } = setup(true, { ...STOPPED, resume_action: 'export' })
    const row = await banner()
    expect(row).toHaveTextContent('Generation stopped 3h ago before it finished · 2 of 4 done')
    expect(within(row).queryByText(/python analyzer.py resume/)).not.toBeInTheDocument()
    await user.click(within(row).getByRole('button', { name: 'Run on the server' }))
    expect(within(row).getByText('python analyzer.py resume --project-id p1 --version-id ver1 --detach')).toBeInTheDocument()
    await user.click(within(row).getByRole('button', { name: /Resume/ }))
    await waitFor(() => expect(resumed).toEqual(['ver1']))
  })

  it('names what did not get its documents, and why', async () => {
    const failed = { ...IDLE, components: [comp('Layer1.Math', 'generated', [DOC('d1')]), comp('Layer1.Util', 'failed'),
      comp('Layer2.Gpio', 'not_requested')], resume_action: 'export' }
    setup(true, failed)
    expect(await banner()).toHaveTextContent('Layer1.Util failed · Components: L1.Util: stopped with exit code 1 · 1 of 3 done')
  })

  it('Resume waits while a run holds the version; a developer gets neither it nor the command', async () => {
    setup(true, { ...STOPPED, resume_action: 'busy' })
    const row = await banner()
    expect(within(row).getByRole('button', { name: /Resume/ })).toBeDisabled()
    expect(within(row).getByRole('button', { name: /Resume/ })).toHaveAttribute('title', expect.stringMatching(/at work on this version/))
  })

  it('a developer sees the stop, not Resume', async () => {
    setup(false, { ...STOPPED, resume_action: 'export' })
    const row = await banner()
    expect(within(row).queryByRole('button', { name: /Resume/ })).not.toBeInTheDocument()
    expect(within(row).queryByRole('button', { name: 'Run on the server' })).not.toBeInTheDocument()
  })

  it('a version with no documents yet shows only when it has a model', async () => {
    const noModel = { ...IDLE, components: IDLE.components.map((c) => ({ ...c, state: 'not_requested', documents: [], in_model: false, layer_parsed: false })) }
    const { container } = setup(true, noModel, { needsModel: true })
    await new Promise((r) => setTimeout(r, 100))
    expect(container).toBeEmptyDOMElement()
  })

  it('"View components" opens the drawer in place; ?components=1 opens it too', async () => {
    const { user } = setup(false, IDLE)
    await user.click(within(await banner()).getByRole('button', { name: 'View components' }))
    expect(await screen.findByRole('dialog', { name: 'Components' })).toHaveTextContent('v1.2.0 · 2 of 4 have documents · 2 layers')
  })

  it('a deep link opens the drawer', async () => {
    setup(false, IDLE, { url: '/?components=1' })
    expect(await screen.findByRole('dialog', { name: 'Components' })).toBeInTheDocument()
  })
})

/* The second row: the version's Word files out of date (R9 `outOfDate` — corrections, or a layer
   added since), and the one update this role may start (WORD_FILE_UPDATES W5). */
describe('GenerationBanner: Word files out of date (the second row)', () => {
  const words = () => screen.findByRole('status', { name: 'Word files' })

  it("alone when nothing else applies; an admin's Update all asks first, then updates every one", async () => {
    const { reexported, user } = setup(true, ADDED, { readiness: BEHIND })
    const row = await words()
    expect(row).toHaveTextContent('2 Word files are out of date · 2 corrections, Layer2 added since')
    expect(screen.queryByRole('button', { name: 'View components' })).not.toBeInTheDocument()
    await user.click(within(row).getByRole('button', { name: 'Update all' }))
    const dialog = await screen.findByRole('dialog', { name: 'Update 2 Word files' })
    await user.click(within(dialog).getByRole('button', { name: /^Update$/ }))
    await waitFor(() => expect(reexported).toEqual([JSON.stringify({ scope: 'out_of_date' })]))
  })

  it('under the generation row when both apply', async () => {
    setup(true, { ...ADDED, components: [...ADDED.components, comp('Layer2.Gpio', 'not_requested')] }, { readiness: BEHIND })
    const card = await banner()
    expect(card).toHaveTextContent('1 component has no documents yet')
    await waitFor(() => expect(card).toHaveTextContent('2 Word files are out of date'))
  })

  it('a developer updates the ones they review (Update them, their components only)', async () => {
    useAuthStore.setState({ user: { id: 'u2', email: 'developer@company.com', name: 'Dev Two' } as never })
    try {
      const { reexported, user } = setup(false, ADDED, { readiness: BEHIND })
      const row = await words()
      await waitFor(() => expect(row).toHaveTextContent('2 Word files are out of date · 1 you review'))
      await user.click(within(row).getByRole('button', { name: 'Update them' }))
      const dialog = await screen.findByRole('dialog', { name: 'Update 1 Word file' })
      await user.click(within(dialog).getByRole('button', { name: /^Update$/ }))
      await waitFor(() => expect(reexported).toEqual([JSON.stringify({ scope: 'out_of_date', components: ['Layer1.App'] })]))
    } finally {
      useAuthStore.setState({ user: null })
    }
  })

  it('a developer who reviews none of them: an admin updates them, no button', async () => {
    setup(false, ADDED, { readiness: BEHIND })
    expect(await words()).toHaveTextContent('2 Word files are out of date · an admin updates them')
    expect(screen.queryByRole('button', { name: /Update/ })).not.toBeInTheDocument()
  })

  it('while a generation holds the version: the button is off, and the row says when', async () => {
    setup(true, ADDED, { readiness: { ...BEHIND, writer: { kind: 'generation', jobId: 'j5', command: 'generate',
      since: null, components: null, componentsDone: 11, componentsTotal: 54, startedBy: null } } })
    const row = await words()
    expect(row).toHaveTextContent('2 Word files are out of date · Update after the generation of v1.2.0 ends.')
    expect(within(row).getByRole('button', { name: 'Update all' })).toBeDisabled()
  })

  it('an update at work: its progress here, not twice', async () => {
    setup(false, { ...RUNNING('reexport'), run: { ...RUNNING('reexport').run, command: 'reexport' } }, { readiness: { ...BEHIND,
      reexport: { jobId: 'jobrx', status: 'running', startedAt: null, completedAt: null, errorMessage: null, scope: 'out_of_date',
        reason: 'update', components: ['Layer1.App', 'Layer1.Math'], componentsDone: 1, startedBy: null } } })
    const card = await banner()
    await waitFor(() => expect(card).toHaveTextContent('Updating Word files… 1 of 2'))
    expect(card).not.toHaveTextContent('components done')
  })

  it("R9 failed closed: can't tell which Word files are out of date — never nothing", async () => {
    setup(true, ADDED, { readiness: 'failed' })
    expect(await words()).toHaveTextContent('Can’t tell which Word files are out of date.')
    expect(screen.queryByRole('button', { name: /Update/ })).not.toBeInTheDocument()
  })

  it("2: a developer's failed update of a component they do not review: no Try again here, its document linked", async () => {
    useAuthStore.setState({ user: { id: 'u2', email: 'developer@company.com', name: 'Dev Two' } as never })
    try {
      // u2 reviews App (d2); they updated Math from its document (d1), and it failed.
      setup(false, ADDED, { readiness: { ...BEHIND, reexport: {
        jobId: 'jobrx', status: 'failed', startedAt: null, completedAt: null, errorMessage: 'pictures could not be drawn',
        scope: 'out_of_date', reason: 'update', components: ['Layer1.Math'], componentsDone: 0,
        startedBy: { userId: 'u2', name: 'Dev Two', initials: 'DT' } } } })
      const row = await words()
      await waitFor(() => expect(row).toHaveTextContent('Update failed — Pictures could not be drawn.'))
      expect(row).toHaveTextContent('Open Math (SWE.3) to try again.')
      expect(within(row).getByRole('link', { name: 'Math (SWE.3)' })).toHaveAttribute('href', '/projects/p1/documents/d1')
      expect(within(row).queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    } finally {
      useAuthStore.setState({ user: null })
    }
  })

  it('a stale component R9 does not list (an older API, nothing out of date): no row', async () => {
    const { container } = setup(true, ADDED)
    await new Promise((r) => setTimeout(r, 100))
    expect(container).toBeEmptyDOMElement()
  })
})
