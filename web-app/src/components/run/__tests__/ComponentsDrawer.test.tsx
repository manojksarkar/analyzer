import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { ComponentsDrawer } from '../ComponentsDrawer'
import { GenerationBanner } from '../GenerationBanner'
import type { ArchLayer, VersionComponent, VersionComponents } from '../../../types'

/* The Components drawer: every component of the version laid out like the Architecture view
   (layer → group → chips); an admin picks the ones without documents and generates them
   (POST …/documents/generate); a developer reads it. */

const one = (id: string, over: Partial<VersionComponent> = {}): VersionComponent => ({
  id, layer: id.split('.')[0], name: id.split('.')[1], state: 'not_requested',
  inModel: true, layerParsed: true, group: null, error: null, documents: [], ...over,
})
const DOC = { id: 'd1', process: 'SWE.3', status: 'approved' as const }

/** The live sample's shape: Layer1 in the model (groups from the API), Layer2 not yet. */
const DATA: VersionComponents = {
  components: [
    one('Layer1.App', { group: 'Support' }),
    one('Layer1.Lib', { group: 'My Sample', state: 'generated', documents: [DOC, { id: 'd2', process: 'SWE.4', status: 'in_review' }] }),
    one('Layer1.Math', { group: 'Support', state: 'stale', documents: [{ id: 'd3', process: 'SWE.3', status: 'in_review' }] }),
    one('Layer1.Sample-Core', { group: 'My Sample', state: 'generating' }),
    one('Layer1.Util', { group: 'My Sample', state: 'failed', error: 'stopped with exit code 1' }),
    one('Layer2.Gpio', { group: 'Platform', inModel: false, layerParsed: false }),
    one('Layer2.Uart', { group: 'Platform', inModel: false, layerParsed: false }),
  ],
  counts: {}, run: null, job: null,
}

function setup(isAdmin: boolean, data: VersionComponents = DATA, layers?: ArchLayer[]) {
  const sent: string[][] = []
  server.use(
    http.post(`${API_BASE_URL}/projects/p1/versions/ver1/documents/generate`, async ({ request }) => {
      const b = (await request.json()) as { components: string[] }
      sent.push(b.components)
      return HttpResponse.json({ job_id: 'job1', status: 'queued', version_id: 'ver1', components: b.components, skipped: [], added_layers: [] }, { status: 202 })
    }),
  )
  const onClose = vi.fn()
  const onStarted = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <ComponentsDrawer projectId="p1" versionId="ver1" versionTag="v0.2" data={data} isAdmin={isAdmin}
        layers={layers} onClose={onClose} onStarted={onStarted} />
    </QueryClientProvider>,
  )
  return { sent, onClose, onStarted, user: userEvent.setup(), dialog: screen.getByRole('dialog', { name: 'Components' }) }
}

const section = (name: string) => screen.getByRole('region', { name })
const chip = (name: string) => screen.getByTitle(new RegExp(`^${name}: `))

describe('ComponentsDrawer', () => {
  it('says how far the version has got, and lays the components out by layer and group', () => {
    const { dialog } = setup(false)
    expect(dialog).toHaveTextContent('v0.2 · 2 of 7 have documents · 2 layers')
    const l1 = section('Layer1')
    expect(l1).toHaveTextContent('2 of 5')
    expect(within(l1).getByText('My Sample')).toBeInTheDocument()
    expect(within(l1).getByText('3 comps')).toBeInTheDocument()
    expect(within(section('Layer2')).getByText('Platform')).toBeInTheDocument()
    // A layer the model lacks says what Generate does.
    expect(within(section('Layer2')).getByText(/Not in this version's model yet — Generate adds layer Layer2/)).toBeInTheDocument()
  })

  it("one word per state, and a chip's tooltip names its documents' review states or its error", () => {
    setup(false)
    expect(chip('Lib')).toHaveAttribute('title', 'Lib: Has documents · SWE.3 Approved · SWE.4 In review')
    expect(chip('Math')).toHaveAttribute('title', 'Math: Out of date · SWE.3 In review')
    expect(chip('Sample-Core')).toHaveAttribute('title', 'Sample-Core: In progress')
    expect(chip('Util')).toHaveAttribute('title', 'Util: Failed · stopped with exit code 1')
    expect(chip('App')).toHaveAttribute('title', 'App: Not started')
  })

  it("without the API's group, the project's architecture places the component; unmatched ones sit under the layer", () => {
    const layers: ArchLayer[] = [{ name: 'Layer1', groups: [{ name: 'Configured', components: [{ name: 'Sample Core' }] }] }]
    setup(false, { ...DATA, components: [one('Layer1.Sample-Core'), one('Layer1.Loose')] }, layers)
    const l1 = section('Layer1')
    expect(within(l1).getByText('Configured')).toBeInTheDocument()
    expect(within(l1).getByText('1 comp')).toBeInTheDocument()
    expect(within(l1).getByTitle(/^Loose: /)).toBeInTheDocument()
    expect(within(l1).queryByText('Other')).not.toBeInTheDocument()
  })

  it('a developer reads it: no chip to pick, no Select, no Generate', () => {
    setup(false)
    expect(screen.queryByRole('button', { name: /^Select/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Generate/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'App' })).not.toBeInTheDocument()
  })

  it('search narrows the chips by name; "Without documents" hides the ones that have theirs', async () => {
    const { user } = setup(false)
    await user.type(screen.getByRole('textbox', { name: 'Find a component' }), 'sample core')
    expect(chip('Sample-Core')).toBeInTheDocument()
    expect(screen.queryByTitle(/^App: /)).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Layer2' })).not.toBeInTheDocument()
    await user.clear(screen.getByRole('textbox', { name: 'Find a component' }))
    await user.click(screen.getByRole('button', { name: 'Without documents 5' }))
    expect(screen.queryByTitle(/^Lib: /)).not.toBeInTheDocument()
    expect(screen.queryByTitle(/^Math: /)).not.toBeInTheDocument()
    expect(chip('App')).toBeInTheDocument()
    await user.type(screen.getByRole('textbox', { name: 'Find a component' }), 'nothing like it')
    expect(screen.getByText('No component matches.')).toBeInTheDocument()
  })

  it('an admin picks chips without documents and generates them: the picked ids are sent', async () => {
    const { sent, onStarted, user } = setup(true)
    expect(screen.getByText("Click the components to generate, or Select a layer's.")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled()
    // Those with documents, or being made, are not buttons.
    expect(screen.queryByRole('button', { name: 'Lib' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Sample-Core' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'App' }))
    await user.click(screen.getByRole('button', { name: 'Util' }))
    expect(screen.getByRole('button', { name: 'App' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    expect(screen.getByText('Uses the analysis already done')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Generate 2' }))
    await waitFor(() => expect(sent).toEqual([['Layer1.App', 'Layer1.Util']]))
    await waitFor(() => expect(onStarted).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: 'Generate' })).toBeDisabled()
  })

  it('while a run is at work on the version, Generate is off and says why (one writer per version)', async () => {
    const { sent, user } = setup(true, { ...DATA, job: { id: 'job9', mode: 'export', status: 'running' } })
    await user.click(screen.getByRole('button', { name: 'App' }))
    const generate = screen.getByRole('button', { name: 'Generate 1' })
    expect(generate).toBeDisabled()
    expect(generate.parentElement).toHaveAttribute('title', 'Generate after the run at work on this version ends.')
    expect(screen.getByText('Generate after the run at work on this version ends.')).toBeInTheDocument()
    expect(sent).toEqual([])
  })

  it("Select picks a layer's visible chips without documents; Clear drops them; a layer the model lacks says it is added first", async () => {
    const { sent, user } = setup(true)
    await user.click(within(section('Layer2')).getByRole('button', { name: 'Select 2' }))
    expect(screen.getByText('2 selected')).toBeInTheDocument()
    expect(screen.getByText('Adds Layer2 first (parse + descriptions), then writes the documents')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.queryByText('2 selected')).not.toBeInTheDocument()
    // With a search, only what shows is selected.
    await user.type(screen.getByRole('textbox', { name: 'Find a component' }), 'app')
    await user.click(within(section('Layer1')).getByRole('button', { name: 'Select 1' }))
    await user.click(screen.getByRole('button', { name: 'Generate 1' }))
    await waitFor(() => expect(sent).toEqual([['Layer1.App']]))
  })

  it('a layer folds', async () => {
    const { user } = setup(false)
    const fold = within(section('Layer1')).getByRole('button', { name: 'Layer1' })
    expect(fold).toHaveAttribute('aria-expanded', 'true')
    await user.click(fold)
    expect(fold).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTitle(/^App: /)).not.toBeInTheDocument()
  })

  it('Esc, the scrim and the X close it', async () => {
    const { onClose, user } = setup(false)
    await user.keyboard('{Escape}')
    expect(onClose).toHaveBeenCalledTimes(1)
    await user.click(document.querySelector('[data-scrim]') as HTMLElement)
    expect(onClose).toHaveBeenCalledTimes(2)
    await user.click(screen.getByRole('button', { name: 'Close' }))
    expect(onClose).toHaveBeenCalledTimes(3)
  })
})

describe('ComponentsDrawer from the banner', () => {
  it('focus moves into the drawer and returns to "View components" when it closes', async () => {
    server.use(http.get(`${API_BASE_URL}/projects/p1/versions/ver1/components`, () => HttpResponse.json({
      version_id: 'ver1', counts: { not_requested: 1 }, run: null, job: null,
      components: [{ component: 'Layer1.App', layer: 'Layer1', name: 'App', state: 'not_requested', in_model: true,
        layer_parsed: true, group: 'Support', error: null, documents: [] }],
    })))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrap = (c: ReactNode) => <MemoryRouter><QueryClientProvider client={client}>{c}</QueryClientProvider></MemoryRouter>
    render(wrap(<GenerationBanner projectId="p1" versionId="ver1" isAdmin={false} />))
    const user = userEvent.setup()
    const open = await screen.findByRole('button', { name: 'View components' })
    await user.click(open)
    const dialog = await screen.findByRole('dialog', { name: 'Components' })
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(dialog.contains(document.activeElement)).toBe(true)
    // The search box: typing narrows the chips at once.
    expect(within(dialog).getByRole('textbox', { name: 'Find a component' })).toHaveFocus()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(open).toHaveFocus()
  })
})
