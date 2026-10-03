import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { ComponentsPanel } from '../components/ComponentsPanel'
import { componentsByLayer, pickable } from '../helpers'
import type { VersionComponent } from '../../../types'

/* Staged generation: a version's components and the documents still to make
   (GET …/versions/{vid}/components, POST …/documents/generate). */

const comp = (component: string, state: string, documents: { id: string; process: string; status: string }[] = []) => ({
  component, layer: component.split('.')[0], name: component.split('.')[1], state, in_model: true,
  error: state === 'failed' ? 'Components: L1.Util: stopped with exit code 1' : null, documents,
})

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
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/versions/ver1/components`, () => HttpResponse.json(body)),
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
  return { sent, cancelled, user: userEvent.setup() }
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
})

describe('the component helpers', () => {
  const view: VersionComponent[] = BODY.components.map((c) => ({
    id: c.component, layer: c.layer, name: c.name, state: c.state as VersionComponent['state'],
    inModel: c.in_model, error: c.error, documents: [],
  }))

  it('groups by layer in order, and only components without documents are pickable', () => {
    expect(componentsByLayer(view).map(([l, cs]) => [l, cs.length])).toEqual([['Layer1', 3], ['Layer2', 1]])
    expect(view.filter(pickable).map((c) => c.id)).toEqual(['Layer1.App', 'Layer1.Util', 'Layer2.Gpio'])
  })
})
