import { useState, type ReactNode } from 'react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import versions from '../../../test/fixtures/captured/versions.json'
import members from '../../../test/fixtures/captured/members.json'
import documentFx from '../../../test/fixtures/captured/document.json'
import { SubbarCtaProvider } from '../../../components/shell/SubbarCta'
import { useUIStore } from '../../../store/ui'
import type { FlowchartEntry } from '../../../types'
import { DocumentInspectorPage } from '..'

/* The reader with a document of many sections (an office SWE.3 has 500+ flowcharts and hundreds
   of tables). #28: typing in one correction box, saving it, or opening a panel must not render
   every section again. Each flowchart figure counts its renders here: one renders again only
   when its own section does. And the smoke test's deep link: a document opened by its address
   shows its own version in the Subbar, not the latest. */

const renders = new Map<string, number>()
vi.mock('../components/FlowchartFigure', () => ({
  FlowchartFigure: ({ chart }: { chart: FlowchartEntry }) => {
    renders.set(chart.label, (renders.get(chart.label) ?? 0) + 1)
    return <span>{`figure ${chart.label}`}</span>
  },
  ImageViewer: () => null,
}))

const slot = (key: string, text: string) => ({
  slotKind: 'description', slotKey: key, text, llmText: text, humanText: null,
  isOverridden: false, isOrphaned: false, canUndo: false, updatedBy: null, updatedAt: null,
})

/** A function's section: its description (a correctable text) and its flowchart. */
const fnSection = (name: string, n: number, text: string) => ({
  id: `fn-${name}`, number: `2.${n}`, title: `${name}()`, level: 3, type: 'flowchart_table', content: null,
  table: null, children: [],
  flowchart_table: {
    description: text, risk: 'Low', capacity: '-', input_name: 'x', output_name: 'y',
    description_slot: slot(`C|U|${name}|int`, text),
    flowcharts: [{ label: name, status: 'drawn', image_url: `https://assets/${name}.svg`, width: 400, height: 900, boxes: 5 }],
  },
})

function renderPayload(firstText: string) {
  return {
    document: {
      cover: { project_name: 'VCU', subtitle: 'Detailed Design', version: 'v1.1.0', layer: 'Layer1', group: 'Full' },
      toc: [],
      sections: [{
        id: 'comp-C', number: '2', title: 'Component C', level: 1, type: 'richtext', content: null, table: null,
        children: [fnSection('alpha', 1, firstText), fnSection('beta', 2, 'Reads.'), fnSection('gamma', 3, 'Writes.')],
      }],
      meta: {
        pipeline_data_available: true, model_data_available: true, source: 'pipeline', layers: ['Layer1'],
        components: ['C'], units_total: 1, functions_total: 3, globals_total: 0,
      },
    },
  }
}

const r9 = {
  stale: false, reason: '', explanation: '', overrideCount: 0, pendingRenders: 0, failedRenders: 0,
  newestOverrideAt: null, oldestDerivationAt: null, reexport: null,
}

function setup() {
  // A document of v1.1.0 (ver2), the version before the latest.
  const doc = { ...documentFx.document, version_id: 'ver2' }
  const state = { text: 'Adds.' }
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/members`, () => HttpResponse.json(members)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: [doc], pagination: { page: 1, per_page: 100, total: 1 } })),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc1`, () => HttpResponse.json({ document: doc })),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc1/render`, () => HttpResponse.json(renderPayload(state.text))),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc1/events`, () => HttpResponse.json({ events: [] })),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver2/export-readiness`, () => HttpResponse.json(r9)),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver2/overrides`, () =>
      HttpResponse.json({ overrides: [], total: 0, limit: 1000, offset: 0 })),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver2/regeneration-queue`, () => HttpResponse.json({ pending: [], total: 0 })),
    http.put(`${API_BASE_URL}/projects/p1/versions/ver2/overrides/slot`, async ({ request }) => {
      const body = (await request.json()) as { slot_key: string; text: string }
      state.text = body.text
      return HttpResponse.json({ ...slot(body.slot_key, body.text), humanText: body.text, isOverridden: true, canUndo: true,
        previousText: 'Adds.', firstEdit: true, queuedForRegeneration: [] })
    }),
  )
  function Layout({ children }: { children: ReactNode }) {
    const [cta, setCta] = useState<HTMLDivElement | null>(null)
    return <><div ref={setCta} data-testid="subbar-cta" /><SubbarCtaProvider slot={cta}>{children}</SubbarCtaProvider></>
  }
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/documents/doc1']}>
        <Routes>
          <Route path="/projects/:projectId/documents/:docId" element={<Layout><DocumentInspectorPage /></Layout>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { state, user: userEvent.setup() }
}

const settle = () => new Promise((r) => setTimeout(r, 150))
const counts = () => Object.fromEntries(renders)

beforeAll(() => {
  // jsdom has no layout: the reader scrolls and measures.
  if (!Element.prototype.scrollIntoView) Element.prototype.scrollIntoView = () => {}
})
afterEach(() => {
  cleanup()
  renders.clear()
  useUIStore.setState({ selectedRef: {}, inspectorPanelCollapsed: false })
})

describe('the reader with many sections', { timeout: 60_000 }, () => {
  it('typing in a box, saving it and opening a panel render only the section it is in', async () => {
    const { state, user } = setup()
    expect(await screen.findByText('figure gamma')).toBeInTheDocument()
    await user.click(within(screen.getByTestId('subbar-cta')).getByRole('button', { name: /EDIT/ }))
    const boxes = await screen.findAllByRole('textbox', { name: 'Correct this text' })
    await settle()
    const before = counts()

    // Typing: the box's own state only.
    fireEvent.change(boxes[0], { target: { value: 'Adds two numbers.' } })
    await settle()
    expect(counts()).toEqual(before)

    // Saving: the render is read again, and only the section whose text changed renders.
    fireEvent.blur(boxes[0])
    await waitFor(() => expect(state.text).toBe('Adds two numbers.'))
    await waitFor(() => expect(renders.get('alpha')).toBeGreaterThan(before.alpha))
    await settle()
    expect(renders.get('beta')).toBe(before.beta)
    expect(renders.get('gamma')).toBe(before.gamma)

    // Opening a panel, and folding the right one.
    const afterSave = counts()
    await user.click(screen.getByRole('tab', { name: /Corrections/ }))
    await user.click(screen.getByRole('button', { name: 'Collapse the panel' }))
    await user.click(screen.getByRole('button', { name: 'Show the panel' }))
    await user.click(screen.getByRole('button', { name: 'Show the document list' }))
    await settle()
    expect(counts()).toEqual(afterSave)
  })

  it("a document opened by its address shows its own version in the Subbar, not the latest", async () => {
    setup()
    expect(await screen.findByText('figure alpha')).toBeInTheDocument()
    await waitFor(() => expect(useUIStore.getState().selectedRef.p1).toEqual({ type: 'version', id: 'ver2' }))
  })
})
