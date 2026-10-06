import { afterEach, beforeAll, beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import projects from '../../../test/fixtures/projects.json'
import { NewProjectPage } from '..'
import { ConfigImport } from '../components/ConfigImport'
import { saveDraft, type WizardDraft } from '../draft'

/* Step 1, Remote (docs/design/BITBUCKET_SUPPORT.md, T5): the access token field is always there
   for a remote URL but an SSH one; the server says which URL it used (a Bitbucket page address
   comes back as its clone URL) and why a sign-in failed; the project is created with no provider -
   the server reads it from the URL. */

const PAGE = 'https://bitbucket.company.com/projects/VCU/repos/vcu-firmware/browse'
const CLONE = 'https://bitbucket.company.com/scm/vcu/vcu-firmware.git'
const NEEDS_TOKEN = 'Authentication failed — this repository needs an access token.'
const BAD_TOKEN = 'Authentication failed — check the access token.'

const draft = (over: Partial<WizardDraft> = {}): WizardDraft => ({
  step: 1, done: [], name: 'VCU', repoSource: 'url', repoUrl: '', branch: '',
  tokenUsed: false, cores: [], layers: [], fileAssignments: {}, members: [], imported: null,
  importKept: [], archEdited: false, ...over,
})

type Body = Record<string, unknown>

/** `answer`: Test Connection's answer to a request body (default: connected, no `repo_url` - an
 *  older server). */
function setup(answer?: (body: Body) => Body) {
  const tests: Body[] = []
  const browsed: Body[] = []
  const created: Body[] = []
  server.use(
    http.post(`${API_BASE_URL}/repositories/test-connection`, async ({ request }) => {
      const body = await request.json() as Body
      tests.push(body)
      return HttpResponse.json(answer?.(body) ?? { connected: true, default_branch: 'main', branches: ['main'], message: 'Connected' })
    }),
    http.post(`${API_BASE_URL}/repositories/browse`, async ({ request }) => {
      browsed.push(await request.json() as Body)
      return HttpResponse.json({ entries: [
        { type: 'folder', name: 'Layer1', path: 'Layer1', children: [{ type: 'file', name: 'a.cpp', path: 'Layer1/a.cpp' }] }] })
    }),
    http.post(`${API_BASE_URL}/projects`, async ({ request }) => {
      created.push(await request.json() as Body)
      return HttpResponse.json({ project: projects.projects[0] }, { status: 201 })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/new']}>
        <Routes>
          <Route path="/projects/new" element={<NewProjectPage />} />
          <Route path="/projects/:id/overview" element={<p>Project overview</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { tests, browsed, created, user: userEvent.setup() }
}

const urlBox = () => screen.getByRole('textbox', { name: 'Repository URL' })
const tokenBox = () => screen.getByLabelText('Access Token')
const testButton = () => screen.getByRole('button', { name: /Test Connection/i })

beforeAll(() => {
  // jsdom has no scrolling; the wizard scrolls to the top on every step.
  if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {}
})
// Each test starts a fresh wizard: a draft the last test's page kept (sessionStorage) would be restored.
beforeEach(() => { sessionStorage.clear() })
afterEach(() => { sessionStorage.clear() })

// The whole wizard renders: its first render is slow on a loaded machine.
describe('Step 1: Remote', { timeout: 60_000 }, () => {
  it('Remote | Local, a Bitbucket placeholder, and the token field with no link and no side note', async () => {
    setup()
    expect(await screen.findByRole('radio', { name: 'Remote' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('radio', { name: 'Local' })).toHaveAttribute('aria-checked', 'false')
    expect(urlBox()).toHaveAttribute('placeholder', CLONE)
    expect(tokenBox()).toHaveAttribute('placeholder', 'Paste the access token')
    expect(tokenBox()).toHaveAttribute('type', 'password')
    expect(screen.queryByText(/Private repository\?/)).toBeNull()
    expect(screen.queryByText(/Optional — for private repos/)).toBeNull()
  })

  it('the token field is hidden for Local and for an SSH URL, and back for an https one', async () => {
    const { user } = setup()
    await screen.findByRole('textbox', { name: 'Repository URL' })
    expect(tokenBox()).toBeInTheDocument()

    for (const ssh of ['ssh://git@bitbucket.company.com:7999/vcu/vcu-firmware.git', 'git@bitbucket.company.com:vcu/vcu-firmware.git']) {
      fireEvent.change(urlBox(), { target: { value: ssh } })
      expect(screen.queryByLabelText('Access Token')).toBeNull()
    }
    fireEvent.change(urlBox(), { target: { value: CLONE } })
    expect(tokenBox()).toBeInTheDocument()

    await user.click(screen.getByRole('radio', { name: 'Local' }))
    expect(screen.queryByLabelText('Access Token')).toBeNull()
    await user.click(screen.getByRole('radio', { name: 'Remote' }))
    expect(tokenBox()).toBeInTheDocument()
  })

  it('an SSH URL is tested without the token typed before', async () => {
    const { user, tests } = setup()
    await screen.findByRole('textbox', { name: 'Repository URL' })
    fireEvent.change(tokenBox(), { target: { value: 'secret-token' } })
    fireEvent.change(urlBox(), { target: { value: 'git@bitbucket.company.com:vcu/vcu-firmware.git' } })
    await user.click(testButton())
    await waitFor(() => expect(tests).toHaveLength(1))
    expect(tests[0]).toEqual({ repo_url: 'git@bitbucket.company.com:vcu/vcu-firmware.git' })
  })

  it('a page address is replaced by the clone URL the server used, and the tree is read from it', async () => {
    const { user, tests, browsed } = setup((b) => ({
      connected: true, default_branch: 'main', branches: ['main'], message: 'Connected · 1 branches found',
      repo_url: b.repo_url === PAGE ? CLONE : b.repo_url,
    }))
    await screen.findByRole('textbox', { name: 'Repository URL' })
    fireEvent.change(urlBox(), { target: { value: PAGE } })
    fireEvent.change(tokenBox(), { target: { value: 'secret-token' } })
    await user.click(testButton())

    await waitFor(() => expect(urlBox()).toHaveValue(CLONE))
    expect(tests[0]).toEqual({ repo_url: PAGE, access_token: 'secret-token' })
    expect(await screen.findByRole('combobox', { name: 'Branch' })).toHaveValue('main')
    await waitFor(() => expect(browsed).toHaveLength(1))
    expect(browsed[0]).toMatchObject({ repo_url: CLONE, access_token: 'secret-token' })
  })

  it('an older server, with no repo_url in its answer, leaves the box as typed', async () => {
    const { user, tests } = setup()
    await screen.findByRole('textbox', { name: 'Repository URL' })
    fireEvent.change(urlBox(), { target: { value: 'https://example.invalid/brake.git' } })
    await user.click(testButton())
    await waitFor(() => expect(tests).toHaveLength(1))
    expect(await screen.findByRole('combobox', { name: 'Branch' })).toHaveValue('main')
    expect(urlBox()).toHaveValue('https://example.invalid/brake.git')
  })

  it.each([
    ['no token sent', '', NEEDS_TOKEN],
    ['a wrong token sent', 'expired-token', BAD_TOKEN],
  ])('a sign-in failure (%s): the message, and the cursor in the token field', async (_, token, message) => {
    const { user, tests } = setup((b) => ({
      connected: false, default_branch: null, branches: [], repo_url: CLONE,
      message: b.access_token ? BAD_TOKEN : NEEDS_TOKEN,
    }))
    await screen.findByRole('textbox', { name: 'Repository URL' })
    fireEvent.change(urlBox(), { target: { value: PAGE } })
    if (token) fireEvent.change(tokenBox(), { target: { value: token } })
    await user.click(testButton())

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(tests[0]).toEqual(token ? { repo_url: PAGE, access_token: token } : { repo_url: PAGE })
    expect(tokenBox()).toHaveFocus()
    expect(urlBox()).toHaveValue(CLONE)                       // the clone URL, for the next try
    expect(screen.queryByRole('combobox', { name: 'Branch' })).toBeNull()
  })

  it('another failure leaves the cursor where it was', async () => {
    const { user } = setup(() => ({
      connected: false, default_branch: null, branches: [], message: 'Could not reach the remote — check the URL and your network.',
    }))
    await screen.findByRole('textbox', { name: 'Repository URL' })
    fireEvent.change(urlBox(), { target: { value: CLONE } })
    await user.click(testButton())
    expect(await screen.findByText(/Could not reach the remote/)).toBeInTheDocument()
    expect(tokenBox()).not.toHaveFocus()
  })

  it('creating the project sends no repo_provider: the server reads it from the URL', async () => {
    saveDraft(draft({
      step: 5, done: [1, 2, 3, 4], repoUrl: CLONE, branch: 'main',
      layers: [{ id: 'l1', name: 'LAYER1', path: 'Layer1', libPaths: [], coreId: null, collapsed: false, groups: [
        { id: 'g1', name: 'G', collapsed: false, comps: [{ id: 'c1', name: 'Core', files: ['Layer1/a.cpp'], collapsed: false }] }] }],
      fileAssignments: { 'Layer1/a.cpp': 'Core' },
    }))
    const { user, created } = setup()
    expect(await screen.findByText(/Every path is on branch main/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Initialize Project/ }))
    await waitFor(() => expect(created).toHaveLength(1))
    expect(created[0]).toMatchObject({ repo_url: CLONE, default_branch: 'main' })
    expect(created[0]).not.toHaveProperty('repo_provider')
    expect(await screen.findByText('Project overview')).toBeInTheDocument()
  })
})

describe('the config card (ConfigImport)', () => {
  it('asks "Have a config file?" and says what it fills, nothing more', () => {
    render(<ConfigImport busy={false} onPick={() => {}} archChanged={false} branch="" checking={false} kept={[]} />)
    expect(screen.getByText('Have a config file?')).toBeInTheDocument()
    expect(screen.getByText('Fills the project, repository, cores and architecture.')).toBeInTheDocument()
    expect(screen.queryByText(/onboard --config/)).toBeNull()
    expect(screen.queryByText(/access token/i)).toBeNull()
    expect(screen.queryByText('Optional')).toBeNull()
    expect(screen.getByRole('button', { name: /Import config/ })).toBeInTheDocument()
  })
})
