import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { NewProjectPage } from '..'
import { clearDraft, loadDraft, saveDraft, type WizardDraft } from '../draft'
import type { ConfigPreview } from '../../../types'

/* #9: a reload took the New Project wizard back to an empty step 1. This tab keeps a draft of it
   now — the step and what was typed — and never the access token or an imported file's text. */

const KEY = 'artifex.newProject.draft.v1'
const TOKEN = 'ghp_secret_never_kept'

const draft = (over: Partial<WizardDraft> = {}): WizardDraft => ({
  step: 2, done: [1], name: 'Brake ECU', repoUrl: 'https://example.invalid/brake.git', branch: 'dev',
  tokenUsed: false, cores: [], layers: [], fileAssignments: {}, members: [], imported: null,
  importKept: [], archEdited: false, ...over,
})

/** `testAnswer`: what Test Connection answers (default: connected, branches dev and main). */
function setup(testAnswer?: () => Response) {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    calls.push(`${request.method} ${new URL(request.url).pathname.replace(/^.*\/api\/v1/, '')}`)
  })
  server.use(
    http.post(`${API_BASE_URL}/repositories/test-connection`, testAnswer ?? (() => HttpResponse.json({
      connected: true, default_branch: 'main', branches: ['dev', 'main'], message: 'Connected',
    }))),
    http.get(`${API_BASE_URL}/repositories/browse`, () => HttpResponse.json({ entries: [] })),
    http.post(`${API_BASE_URL}/repositories/browse`, () => HttpResponse.json({ entries: [] })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/new']}>
        <Routes>
          <Route path="/projects/new" element={<NewProjectPage />} />
          <Route path="/projects" element={<p>Projects list</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
  return { calls, ...render(ui) }
}

beforeAll(() => {
  // jsdom has no scrolling; the wizard scrolls to the top on every step.
  if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {}
})
afterEach(() => { server.events.removeAllListeners('request:start'); sessionStorage.clear() })

describe('the wizard draft (draft.ts)', () => {
  it('keeps the step and the fields, drops the imported file text and anything else', () => {
    const preview = { draft: {}, report: [], expectedUploads: {}, repositoryChecked: true } as unknown as ConfigPreview
    saveDraft({ ...draft({ imported: { fileName: 'brake.json', preview, text: `{"token":"${TOKEN}"}` } as never }), token: TOKEN } as never)
    const raw = sessionStorage.getItem(KEY) ?? ''
    expect(raw).not.toContain(TOKEN)
    expect(loadDraft()).toEqual(draft({ imported: { fileName: 'brake.json', preview } }))
  })

  it('reads nothing from a missing, broken or foreign draft', () => {
    expect(loadDraft()).toBeNull()
    sessionStorage.setItem(KEY, '{not json')
    expect(loadDraft()).toBeNull()
    sessionStorage.setItem(KEY, JSON.stringify({ step: 'two' }))
    expect(loadDraft()).toBeNull()
    clearDraft()
    expect(sessionStorage.getItem(KEY)).toBeNull()
  })
})

// The whole wizard renders: its first render is slow on a loaded machine.
describe('NewProjectPage across a reload', { timeout: 60_000 }, () => {
  it('a reload keeps what was typed, never the token, and asks for the token again', async () => {
    const first = setup()
    fireEvent.change(await screen.findByPlaceholderText('e.g. VCU Engine Firmware'), { target: { value: 'Brake ECU' } })
    fireEvent.change(screen.getByPlaceholderText('https://github.com/org/repo.git'), { target: { value: 'https://example.invalid/brake.git' } })
    fireEvent.click(screen.getByText('Private repository? Add an access token'))
    fireEvent.change(screen.getByPlaceholderText('ghp_xxxxxxxxxxxxxxxxxxxx'), { target: { value: TOKEN } })
    await waitFor(() => expect(loadDraft()?.name).toBe('Brake ECU'))
    expect(sessionStorage.getItem(KEY)).not.toContain(TOKEN)
    expect(loadDraft()).toMatchObject({ repoUrl: 'https://example.invalid/brake.git', tokenUsed: true })

    first.unmount()                                           // the reload
    const { calls } = setup()
    expect(await screen.findByDisplayValue('Brake ECU')).toBeInTheDocument()
    expect(screen.getByDisplayValue('https://example.invalid/brake.git')).toBeInTheDocument()
    expect(screen.getByPlaceholderText('ghp_xxxxxxxxxxxxxxxxxxxx')).toHaveValue('')
    expect(screen.getByText(/Enter the access token again/)).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 300))
    expect(calls.filter((c) => c.endsWith('/repositories/test-connection'))).toEqual([])   // waits for the token
  })

  it('opens on the step it was on, and connects a public repository again by itself', async () => {
    saveDraft(draft())
    const { calls } = setup()
    expect(await screen.findByText('Step 2 of 5')).toBeInTheDocument()
    await waitFor(() => expect(calls.filter((c) => c.endsWith('/repositories/test-connection'))).toHaveLength(1))
  })

  /* Review of cded9b4: a failed automatic test on a restore cleared the branch, and the draft
     kept the cleared one — the next reload had lost it. */
  it.each([
    ['refuses', () => HttpResponse.json({ connected: false, default_branch: null, branches: [], message: 'Repository unreachable' })],
    ['fails', () => HttpResponse.json({ detail: { message: 'Bad gateway' } }, { status: 502 })],
  ])('a restore whose automatic test %s keeps the branch in the draft', async (_, answer) => {
    saveDraft(draft({ step: 1 }))
    const { calls } = setup(answer)
    await waitFor(() => expect(calls.filter((c) => c.endsWith('/repositories/test-connection'))).toHaveLength(1))
    expect(await screen.findByText(/Repository unreachable|Bad gateway|failed/i)).toBeInTheDocument()
    await new Promise((r) => setTimeout(r, 100))
    expect(loadDraft()?.branch).toBe('dev')
  })

  it('closing the wizard drops the draft', async () => {
    saveDraft(draft())
    setup()
    await screen.findByText('Step 2 of 5')
    await userEvent.setup().click(screen.getByRole('button', { name: /Back to Projects/ }))
    expect(await screen.findByText('Projects list')).toBeInTheDocument()
    expect(sessionStorage.getItem(KEY)).toBeNull()
  })
})
