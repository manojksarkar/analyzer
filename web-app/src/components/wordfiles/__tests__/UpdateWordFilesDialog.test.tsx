import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useToastStore } from '../../ui/Toast'
import { useWordFilesStore } from '../../../store/wordFiles'
import { UpdateWordFilesDialog } from '../UpdateWordFilesDialog'
import type { OutOfDateFile } from '../../../types'
import type { UpdateAsk } from '../../../lib/wordFiles'

/* The confirm dialog every update a button starts on its own asks first (WORD_FILE_UPDATES W0):
   the files it writes with why, the notes, an admin's Rebuild all, and what it sends. */

const BRAKE = 'Layer1.Brake-Controller'
const HVAC = 'Layer1.HVAC-Ctrl'
const f = (documentId: string, component: string, name: string, docType: string, over: Partial<OutOfDateFile> = {}): OutOfDateFile => ({
  documentId, component, name, docType, why: ['corrections'], corrections: 2, pictures: 0, layer: null, updating: false, ...over,
})
const FILES = [
  f('b3', BRAKE, 'Brake Controller', 'SWE.3'),
  f('b4', BRAKE, 'Brake Controller', 'SWE.4'),
  f('h4', HVAC, 'HVAC Ctrl', 'SWE.4', { why: ['layerAdded'], corrections: 0, layer: 'HAL_LAYER' }),
]
const NAMES: Record<string, string> = { [BRAKE]: 'Brake Controller', [HVAC]: 'HVAC Ctrl' }
const words = { versionTag: 'v1.2.0', nameOf: (c: string) => NAMES[c] ?? c }
const URL = `${API_BASE_URL}/projects/p1/versions/v1/reexport`

function setup(ask: UpdateAsk, answer: () => Response = () => HttpResponse.json({
  job_id: 'job1', status: 'queued', version_id: 'v1', scope: 'out_of_date', components: [BRAKE], joined: false,
}, { status: 202 })) {
  const sent: unknown[] = []
  server.use(http.post(URL, async ({ request }) => { sent.push(await request.json()); return answer() }))
  const onClose = vi.fn()
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrap = (c: ReactNode) => <QueryClientProvider client={client}>{c}</QueryClientProvider>
  render(wrap(
    <UpdateWordFilesDialog projectId="p1" versionId="v1" ask={ask} files={FILES} rebuildCount={5}
      documentId="b3" words={words} onClose={onClose} />,
  ))
  return { sent, onClose, user: userEvent.setup() }
}

afterEach(() => {
  useToastStore.setState({ toasts: [] })
  useWordFilesStore.setState({ pending: {}, justUpdated: {} })
})

describe('UpdateWordFilesDialog', () => {
  it("lists the files it writes, each with why, says what waits, and sends the update", async () => {
    const { sent, onClose, user } = setup({ components: [BRAKE] })
    expect(screen.getByText('Update 2 Word files')).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Word files it writes' })
    expect(within(list).getAllByRole('listitem').map((li) => li.textContent)).toEqual([
      'Brake Controller (SWE.3) · 2 corrections not in it',
      'Brake Controller (SWE.4) · 2 corrections not in it',
    ])
    expect(screen.getByText('Corrections to Brake Controller wait until it is done.')).toBeInTheDocument()
    expect(screen.getByText('Approved files are not changed.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Update$/ }))
    expect(onClose).toHaveBeenCalled()
    await waitFor(() => expect(sent).toEqual([{ scope: 'out_of_date', components: [BRAKE], document_id: 'b3' }]))
  })

  it("an admin's Update all: every file out of date, both reasons, and no components sent", async () => {
    const { sent, user } = setup({ components: null })
    expect(screen.getByText('Update 3 Word files')).toBeInTheDocument()
    expect(screen.getByText(/HVAC Ctrl \(SWE\.4\)/).textContent).toBe('HVAC Ctrl (SWE.4) · HAL_LAYER added since')
    expect(screen.getByText('Corrections to Brake Controller and HVAC Ctrl wait until it is done.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Update$/ }))
    await waitFor(() => expect(sent).toEqual([{ scope: 'out_of_date', document_id: 'b3' }]))
  })

  it("an admin's Rebuild all: its count and its cost, scope all", async () => {
    const { sent, user } = setup({ components: null, rebuild: true })
    expect(screen.getByText('Rebuild 5 Word files')).toBeInTheDocument()
    expect(screen.queryByRole('list')).toBeNull()
    expect(screen.getByText('Rewrites every file. Takes longer.')).toBeInTheDocument()
    expect(screen.getByText('Corrections to v1.2.0 wait until it is done.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Rebuild$/ }))
    await waitFor(() => expect(sent).toEqual([{ scope: 'all' }]))
  })

  it('from a download: the download starts when it is done (it waits on the job)', async () => {
    const { user } = setup({ components: [BRAKE], download: { docId: 'b3', fileName: 'b.docx' } })
    expect(screen.getByText('The download starts when it is done.')).toBeInTheDocument()
    expect(screen.queryByText('Approved files are not changed.')).toBeNull()
    await user.click(screen.getByRole('button', { name: /^Update$/ }))
    await waitFor(() => expect(useWordFilesStore.getState().pending.job1?.[0]).toMatchObject({ docId: 'b3', fileName: 'b.docx' }))
  })

  it('nothing out of date in what it asks: says so, and Update is off', () => {
    setup({ components: ['Layer1.Other'] })
    expect(screen.getByText('Nothing is out of date now.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Update$/ })).toBeDisabled()
  })

  it('refused because another update runs: says after which one, in one sentence', async () => {
    const { user } = setup({ components: [BRAKE], },
      () => HttpResponse.json({ detail: { code: 'REEXPORT_RUNNING', message: 'busy', status: 409,
        job_id: 'job9', scope: 'out_of_date', components: [HVAC] } }, { status: 409 }))
    await user.click(screen.getByRole('button', { name: /^Update$/ }))
    await waitFor(() => expect(useToastStore.getState().toasts.map((t) => t.title))
      .toEqual(['Update after the update of HVAC Ctrl ends.']))
  })

  it("a developer's update beyond their reach (403 NOT_YOUR_DOCUMENTS): open its document to update it", async () => {
    const { user } = setup({ components: [HVAC] },
      () => HttpResponse.json({ detail: { code: 'NOT_YOUR_DOCUMENTS', message: 'no', status: 403, components: [HVAC] } }, { status: 403 }))
    await user.click(screen.getByRole('button', { name: /^Update$/ }))
    await waitFor(() => expect(useToastStore.getState().toasts[0]).toMatchObject({ title: 'Not updated.', description: 'Open HVAC Ctrl to update it.' }))
  })
})
