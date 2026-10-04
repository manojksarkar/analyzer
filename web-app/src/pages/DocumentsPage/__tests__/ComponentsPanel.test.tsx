import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { ComponentsPanel } from '../components/ComponentsPanel'
import { addsLayer, componentsByLayer, layerNote, layersAdded, pickable } from '../helpers'
import type { VersionComponent } from '../../../types'

/* Staged generation: a version's components and the documents still to make
   (GET …/versions/{vid}/components, POST …/documents/generate). */

const comp = (component: string, state: string, documents: { id: string; process: string; status: string }[] = []) => ({
  component, layer: component.split('.')[0], name: component.split('.')[1], state, in_model: true,
  layer_parsed: true,
  error: state === 'failed' ? 'Components: L1.Util: stopped with exit code 1' : null, documents,
})

/** Named by the version's config in a layer the model lacks yet. */
const outside = (component: string) => ({ ...comp(component, 'not_requested'), in_model: false, layer_parsed: false })

/** Layer2 added to a version that had Layer1: Math's documents are stale, Can is not in the model. */
const ADDED = {
  version_id: 'ver1',
  components: [
    comp('Layer1.Math', 'stale', [{ id: 'd1', process: 'SWE.3', status: 'in_review' }]),
    comp('Layer1.App', 'generated', [{ id: 'd2', process: 'SWE.3', status: 'in_review' }]),
    outside('Layer3.Can'),
    outside('Layer3.Lin'),
  ],
  counts: { generated: 1, stale: 1, not_requested: 2 },
  run: null,
  job: null,
}

const BODY = {
  version_id: 'ver1',
  components: [
    comp('Layer1.Math', 'generated', [{ id: 'd1', process: 'SWE.3', status: 'approved' }, { id: 'd2', process: 'SWE.4', status: 'in_review' }]),
    comp('Layer1.App', 'not_requested'),
    comp('Layer1.Util', 'failed'),
    comp('Layer2.Gpio', 'stopped'),
  ],
  counts: { generated: 1, not_requested: 1, failed: 1, stopped: 1 },
  run: {
    command: 'generate', alive: false, stopped: true, outcome: 'running', host: 'box',
    started_at: '2026-10-01T09:00:00Z', finished_at: null, stage: 'LLM-description-pass1',
    done: 10, total: 40, stage_started_at: '2026-10-01T09:00:00Z', progress_at: '2026-10-01T10:00:00Z',
  },
}

const RUNNING = (mode: string) => ({
  ...BODY,
  run: { ...BODY.run, command: 'export', alive: true, stopped: false, stage: 'flowcharts', done: 18, total: 40 },
  job: { id: 'job9', mode, status: 'running' },
})

function setup(isAdmin: boolean, body: object = BODY) {
  const sent: string[][] = []
  const cancelled: string[] = []
  const reexported: string[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/versions/ver1/components`, () => HttpResponse.json(body)),
    http.post(`${API_BASE_URL}/projects/p1/versions/ver1/reexport`, () => {
      reexported.push('ver1')
      return HttpResponse.json({ job_id: 'jobrx', status: 'queued' }, { status: 202 })
    }),
    http.post(`${API_BASE_URL}/projects/p1/jobs/:jobId/cancel`, ({ params }) => {
      cancelled.push(String(params.jobId))
      return HttpResponse.json({ job: null })
    }),
    http.post(`${API_BASE_URL}/projects/p1/versions/ver1/documents/generate`, async ({ request }) => {
      const b = (await request.json()) as { components: string[] }
      sent.push(b.components)
      return HttpResponse.json({ job_id: 'job1', status: 'queued', version_id: 'ver1', components: b.components, skipped: [] }, { status: 202 })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrap = (c: ReactNode) => <QueryClientProvider client={client}>{c}</QueryClientProvider>
  render(wrap(<ComponentsPanel projectId="p1" versionId="ver1" isAdmin={isAdmin} />))
  return { sent, cancelled, reexported, user: userEvent.setup() }
}

describe('ComponentsPanel', () => {
  it('shows each component of the layers with its state and documents', async () => {
    setup(false)
    expect(await screen.findByText(/1 of 4 generated/)).toBeInTheDocument()
    expect(screen.getByText('SWE.3 Approved · SWE.4 In review')).toBeInTheDocument()
    expect(screen.getByText('Not generated')).toBeInTheDocument()
    expect(screen.getByText('Layer1 · 1 of 3 generated')).toBeInTheDocument()
    expect(screen.getByText(/stopped with exit code 1/)).toBeInTheDocument()
  })

  it('a run cut short says so, with the command that continues it', async () => {
    setup(false)
    expect(await screen.findByText(/stopped .* before it finished/)).toBeInTheDocument()
    expect(screen.getByText('python analyzer.py resume --project-id p1 --version-id ver1 --detach')).toBeInTheDocument()
  })

  it('a developer reads; only an admin ticks and generates', async () => {
    setup(false)
    await screen.findByText(/1 of 4 generated/)
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Generate/ })).not.toBeInTheDocument()
  })

  it('an admin generates the components ticked: only ones without documents can be', async () => {
    const { sent, user } = setup(true)
    await screen.findByText(/1 of 4 generated/)
    expect(screen.queryByRole('checkbox', { name: 'Generate Math' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Generate App' }))
    await user.click(screen.getByRole('checkbox', { name: 'Generate Gpio' }))
    await user.click(screen.getByRole('button', { name: /Generate 2/ }))
    await waitFor(() => expect(sent).toEqual([['Layer1.App', 'Layer2.Gpio']]))
  })

  it('an admin stops the documents being added: what is finished stays', async () => {
    const { cancelled, user } = setup(true, RUNNING('export'))
    expect(await screen.findByText(/Running export — flowcharts 18\/40 \(45%\)/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Stop' }))
    const dialog = await screen.findByRole('dialog', { name: 'Stop making these documents?' })
    expect(within(dialog).getByText(/Components already finished keep their documents/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Stop' }))
    await waitFor(() => expect(cancelled).toEqual(['job9']))
  })

  it("stopping the version's own run says the version goes with it", async () => {
    const { cancelled, user } = setup(true, RUNNING('auto'))
    await user.click(await screen.findByRole('button', { name: 'Stop' }))
    const dialog = await screen.findByRole('dialog', { name: 'Cancel this generation?' })
    expect(within(dialog).getByText(/this version is removed/)).toBeInTheDocument()
    await user.click(within(dialog).getByRole('button', { name: 'Keep running' }))
    expect(cancelled).toEqual([])
  })

  it('a developer sees the run, but no Stop', async () => {
    setup(false, RUNNING('export'))
    expect(await screen.findByText(/Running export/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('no Stop when the API does not say which job is at work (an older API)', async () => {
    setup(true, { ...RUNNING('export'), job: undefined })
    expect(await screen.findByText(/Running export/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Stop' })).not.toBeInTheDocument()
  })

  it('select all takes every component without documents', async () => {
    const { user } = setup(true)
    await user.click(await screen.findByRole('button', { name: 'Select all not generated (3)' }))
    expect(screen.getByRole('button', { name: /Generate 3/ })).toBeEnabled()
  })

  it('a stale component says so, and an admin re-exports the version', async () => {
    const { reexported, user } = setup(true, ADDED)
    expect(await screen.findByText('Stale — re-export')).toBeInTheDocument()
    expect(screen.getByText(/1 of 4 generated · 1 stale · 2 not generated/)).toBeInTheDocument()
    expect(screen.getByText(/1 component is stale: a layer added to the model since/)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox', { name: 'Generate Math' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Re-export' }))
    await waitFor(() => expect(reexported).toEqual(['ver1']))
  })

  it('a developer sees a stale component, but no Re-export', async () => {
    setup(false, ADDED)
    expect(await screen.findByText(/an admin starts it/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Re-export' })).not.toBeInTheDocument()
  })

  it('a component of a layer the model lacks is pickable: Generate adds the layer', async () => {
    const { sent, user } = setup(true, ADDED)
    expect(await screen.findByText(
      "Not in this version's model yet — Generate adds layer Layer3 (parse + descriptions for that layer; Layer1 documents may be marked stale)",
    )).toBeInTheDocument()
    await user.click(screen.getByRole('checkbox', { name: 'Generate Can' }))
    expect(screen.getByText('Adds layer Layer3 first: parse + descriptions, then the documents.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Generate 1/ }))
    await waitFor(() => expect(sent).toEqual([['Layer3.Can']]))
  })
})

describe('the component helpers', () => {
  const view: VersionComponent[] = BODY.components.map((c) => ({
    id: c.component, layer: c.layer, name: c.name, state: c.state as VersionComponent['state'],
    inModel: c.in_model, layerParsed: c.layer_parsed, error: c.error, documents: [],
  }))
  const one = (id: string, over: Partial<VersionComponent>): VersionComponent => ({
    id, layer: id.split('.')[0], name: id.split('.')[1], state: 'not_requested',
    inModel: true, layerParsed: true, error: null, documents: [], ...over,
  })

  it('groups by layer in order, and only components without documents are pickable', () => {
    expect(componentsByLayer(view).map(([l, cs]) => [l, cs.length])).toEqual([['Layer1', 3], ['Layer2', 1]])
    expect(view.filter(pickable).map((c) => c.id)).toEqual(['Layer1.App', 'Layer1.Util', 'Layer2.Gpio'])
  })

  it('outside the model: pickable when its layer is to be added, never when the layer is parsed', () => {
    const toAdd = one('Layer3.Can', { inModel: false, layerParsed: false })
    const noSource = one('Layer1.Ghost', { inModel: false, layerParsed: true })
    const stale = one('Layer1.Math', { state: 'stale', documents: [{ id: 'd1', process: 'SWE.3', status: 'in_review' }] })
    expect([toAdd, noSource, stale].filter(pickable).map((c) => c.id)).toEqual(['Layer3.Can'])
    expect(addsLayer(toAdd) && !addsLayer(noSource)).toBe(true)
    expect(layersAdded([toAdd, one('Layer2.Lin', { inModel: false, layerParsed: false }), stale])).toEqual(['Layer2', 'Layer3'])
  })

  it('a note only under a layer the model lacks, naming the layers whose documents may go stale', () => {
    const comps = [one('Layer1.Math', {}), one('Layer3.Can', { inModel: false, layerParsed: false })]
    expect(layerNote('Layer1', comps)).toBeNull()
    expect(layerNote('Layer3', comps)).toMatch(/Generate adds layer Layer3 .*Layer1 documents may be marked stale/)
  })
})
