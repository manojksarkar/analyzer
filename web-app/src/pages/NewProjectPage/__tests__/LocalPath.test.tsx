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
import { saveDraft, type WizardDraft } from '../draft'

/* Step 1's repository is a Git URL or a local path: a git repository's folder on the server
   ArtiFex runs on, typed or picked with Browse (GET /repositories/local-folders). */

const KEY = 'artifex.newProject.draft.v1'

const draft = (over: Partial<WizardDraft> = {}): WizardDraft => ({
  step: 1, done: [], name: 'Brake ECU', repoSource: 'url', repoUrl: '', branch: '',
  tokenUsed: false, cores: [], layers: [], fileAssignments: {}, members: [], imported: null,
  importKept: [], archEdited: false, ...over,
})

const FOLDERS: Record<string, unknown> = {
  '': { path: '', parent: null, limited: false, truncated: false, folders: [{ name: 'D:/', path: 'D:/', git: false }] },
  'D:/': { path: 'D:/', parent: '', limited: false, truncated: false, folders: [{ name: 'src', path: 'D:/src', git: false }] },
  'D:/src': { path: 'D:/src', parent: 'D:/', limited: false, truncated: false, folders: [
    { name: 'docs', path: 'D:/src/docs', git: false }, { name: 'vcu-firmware', path: 'D:/src/vcu-firmware', git: true }] },
}

function setup() {
  const tests: Record<string, unknown>[] = []
  const created: Record<string, unknown>[] = []
  server.use(
    http.post(`${API_BASE_URL}/repositories/test-connection`, async ({ request }) => {
      tests.push(await request.json() as Record<string, unknown>)
      return HttpResponse.json({ connected: true, default_branch: 'main', branches: ['main'], message: 'Connected' })
    }),
    http.post(`${API_BASE_URL}/repositories/browse`, () => HttpResponse.json({ entries: [
      { type: 'folder', name: 'Layer1', path: 'Layer1', children: [{ type: 'file', name: 'a.cpp', path: 'Layer1/a.cpp' }] }] })),
    http.get(`${API_BASE_URL}/repositories/local-folders`, ({ request }) => {
      const path = new URL(request.url).searchParams.get('path') ?? ''
      return FOLDERS[path] ? HttpResponse.json(FOLDERS[path])
        : HttpResponse.json({ detail: { code: 'NOT_FOUND', message: 'No such folder.', status: 404 } }, { status: 404 })
    }),
    http.post(`${API_BASE_URL}/projects`, async ({ request }) => {
      created.push(await request.json() as Record<string, unknown>)
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
  return { tests, created, user: userEvent.setup() }
}

const urlBox = () => screen.getByRole('textbox', { name: 'Repository URL' })
const folderBox = () => screen.getByRole('textbox', { name: 'Repository folder' })
const source = (name: 'Git URL' | 'Local path') => screen.getByRole('radio', { name })

beforeAll(() => {
  // jsdom has no scrolling; the wizard scrolls to the top on every step.
  if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {}
})
// Each test starts a fresh wizard: a draft the last test's page kept (sessionStorage) would be
// restored - before each test too, as that page may write it again while it is taken down.
beforeEach(() => { sessionStorage.clear() })
afterEach(() => { sessionStorage.clear() })

// The whole wizard renders: its first render is slow on a loaded machine.
describe('Step 1: Git URL | Local path', { timeout: 60_000 }, () => {
  it('each choice keeps its own text', async () => {
    const { user } = setup()
    fireEvent.change(await screen.findByRole('textbox', { name: 'Repository URL' }), { target: { value: 'https://example.invalid/brake.git' } })
    expect(source('Git URL')).toHaveAttribute('aria-checked', 'true')

    await user.click(source('Local path'))
    expect(source('Local path')).toHaveAttribute('aria-checked', 'true')
    expect(folderBox()).toHaveValue('')
    expect(folderBox()).toHaveAttribute('placeholder', 'D:/src/vcu-firmware')
    fireEvent.change(folderBox(), { target: { value: 'D:/src/vcu-firmware' } })

    await user.click(source('Git URL'))
    expect(urlBox()).toHaveValue('https://example.invalid/brake.git')
    expect(urlBox()).toHaveAttribute('placeholder', 'https://github.com/org/repo.git')
    await user.click(source('Local path'))
    expect(folderBox()).toHaveValue('D:/src/vcu-firmware')
  })

  it('a path typed as a URL: "Use Local path" switches and takes it along', async () => {
    const { user } = setup()
    fireEvent.change(await screen.findByRole('textbox', { name: 'Repository URL' }), { target: { value: 'D:\\src\\vcu-firmware' } })
    expect(screen.getByText(/This looks like a folder path, not a URL\./)).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Use Local path' }))
    expect(source('Local path')).toHaveAttribute('aria-checked', 'true')
    expect(folderBox()).toHaveValue('D:\\src\\vcu-firmware')
    expect(screen.queryByText(/This looks like a folder path/)).toBeNull()
    await user.click(source('Git URL'))
    expect(urlBox()).toHaveValue('')
  })

  it('Local path: no token, a hint and Browse; Test Connection sends the path without its quotes', async () => {
    const { user, tests } = setup()
    await screen.findByRole('textbox', { name: 'Repository URL' })
    await user.click(screen.getByText('Private repository? Add an access token'))
    fireEvent.change(screen.getByPlaceholderText('ghp_xxxxxxxxxxxxxxxxxxxx'), { target: { value: 'ghp_secret' } })

    await user.click(source('Local path'))
    expect(screen.queryByText('Private repository? Add an access token')).toBeNull()
    expect(screen.queryByPlaceholderText('ghp_xxxxxxxxxxxxxxxxxxxx')).toBeNull()
    expect(screen.getByText(/A git repository on the server ArtiFex runs on/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /BROWSE/ })).toBeInTheDocument()

    fireEvent.change(folderBox(), { target: { value: '"D:\\src\\vcu-firmware"' } })
    await user.click(screen.getByRole('button', { name: /Test Connection/i }))
    await waitFor(() => expect(tests).toHaveLength(1))
    expect(tests[0]).toEqual({ repo_url: 'D:\\src\\vcu-firmware', repo_provider: 'local' })
    expect(folderBox()).toHaveValue('D:\\src\\vcu-firmware')
  })

  it('a missing folder says "Enter the repository folder"', async () => {
    const { user } = setup()
    await user.click(await screen.findByRole('radio', { name: 'Local path' }))
    fireEvent.change(screen.getByPlaceholderText('e.g. VCU Engine Firmware'), { target: { value: 'Brake ECU' } })
    await user.click(screen.getByRole('button', { name: /Continue/ }))
    expect(await screen.findByText('Enter the repository folder')).toBeInTheDocument()
  })

  it('Browse: a repository picked goes into the field, and the connection is tested at once', async () => {
    const { user, tests } = setup()
    await user.click(await screen.findByRole('radio', { name: 'Local path' }))
    await user.click(screen.getByRole('button', { name: /BROWSE/ }))
    expect(await screen.findByRole('dialog', { name: 'Choose a git repository on the server' })).toBeInTheDocument()
    await user.click(await screen.findByRole('button', { name: /^D:\// }))
    await user.click(await screen.findByRole('button', { name: /^src\// }))
    await user.click(await screen.findByRole('button', { name: /^vcu-firmware/ }))
    await user.click(screen.getByRole('button', { name: 'Use this repository' }))

    expect(screen.queryByRole('dialog')).toBeNull()
    expect(folderBox()).toHaveValue('D:/src/vcu-firmware')
    await waitFor(() => expect(tests).toHaveLength(1))
    expect(tests[0]).toMatchObject({ repo_url: 'D:/src/vcu-firmware' })
    expect(await screen.findByRole('combobox', { name: 'Branch' })).toHaveValue('main')
  })

  it('a restored draft with a local path opens in Local path mode', async () => {
    saveDraft(draft({ repoSource: 'local', repoUrl: 'D:/src/vcu-firmware' }))
    setup()
    expect(await screen.findByRole('textbox', { name: 'Repository folder' })).toHaveValue('D:/src/vcu-firmware')
    expect(source('Local path')).toHaveAttribute('aria-checked', 'true')
  })

  it('a draft from before the switch: a path opens in Local path mode', async () => {
    const old: Partial<WizardDraft> = draft({ repoUrl: 'D:/src/vcu-firmware' })
    delete old.repoSource
    sessionStorage.setItem(KEY, JSON.stringify(old))
    setup()
    expect(await screen.findByRole('textbox', { name: 'Repository folder' })).toHaveValue('D:/src/vcu-firmware')
  })

  it('an imported config naming a path fills Local path', async () => {
    server.use(http.post(`${API_BASE_URL}/projects/config/preview`, () => HttpResponse.json({
      draft: { name: 'Brake ECU', repo_url: 'D:/src/brake', branch: 'main', architecture_layers: [], cores: [], settings: {} },
      expected_uploads: {}, report: [], repository_checked: false,
    })))
    setup()
    const input = await waitFor(() => {
      const el = document.querySelector('input[type="file"][accept=".json,.jsonc"]')
      expect(el).not.toBeNull()
      return el as HTMLInputElement
    })
    fireEvent.change(input, { target: { files: [new File(['{}'], 'brake.json')] } })
    expect(await screen.findByRole('textbox', { name: 'Repository folder' })).toHaveValue('D:/src/brake')
    expect(source('Local path')).toHaveAttribute('aria-checked', 'true')
  })

  it('creating the project sends the folder as a local repository, with no token', async () => {
    saveDraft(draft({
      step: 5, done: [1, 2, 3, 4], repoSource: 'local', repoUrl: 'D:/src/vcu-firmware', branch: 'main',
      layers: [{ id: 'l1', name: 'LAYER1', path: 'Layer1', libPaths: [], coreId: null, collapsed: false, groups: [
        { id: 'g1', name: 'G', collapsed: false, comps: [{ id: 'c1', name: 'Core', files: ['Layer1/a.cpp'], collapsed: false }] }] }],
      fileAssignments: { 'Layer1/a.cpp': 'Core' },
    }))
    const { user, created } = setup()
    expect(await screen.findByText(/Every path is on branch main/)).toBeInTheDocument()
    expect(screen.getByText('Repository folder')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Initialize Project/ }))
    await waitFor(() => expect(created).toHaveLength(1))
    expect(created[0]).toMatchObject({ repo_url: 'D:/src/vcu-firmware', repo_provider: 'local', default_branch: 'main' })
    expect(created[0]).not.toHaveProperty('access_token')
    expect(await screen.findByText('Project overview')).toBeInTheDocument()
  })
})
