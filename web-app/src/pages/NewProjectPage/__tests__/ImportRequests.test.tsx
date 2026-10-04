import { afterEach, beforeAll, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { NewProjectPage } from '..'

/* Importing a config asks the API a fixed number of times, then nothing more until the user does
   something: the "Add member" search on step 4 once asked GET /users/search without end (a hook
   handed its effect a new object every render). Every request the page makes is counted. */

const preview = {
  draft: {
    name: 'Brake ECU',
    repo_url: 'https://example.invalid/brake.git',
    branch: 'dev',
    architecture_layers: [{
      name: 'Layer1', path: 'Layer1', lib_paths: [], core: 'Core1',
      groups: [{ name: 'My Sample', components: [{ name: 'Core', files: ['Layer1/Sample/Core'] }] }],
    }],
    cores: [{ name: 'Core1', macros: null, data_dictionary: null, compile_commands: null }],
    settings: {},
  },
  expected_uploads: {},
  report: [{ level: 'filled', text: 'Architecture: 1 layer.', topic: 'architecture' }],
  repository_checked: false,
}

function setup() {
  const calls: string[] = []
  server.events.on('request:start', ({ request }) => {
    calls.push(`${request.method} ${new URL(request.url).pathname.replace(/^.*\/api\/v1/, '')}`)
  })
  server.use(
    http.post(`${API_BASE_URL}/projects/config/preview`, () => HttpResponse.json(preview)),
    http.post(`${API_BASE_URL}/repositories/test-connection`, () => HttpResponse.json({
      connected: true, default_branch: 'dev', branches: ['dev', 'main'], message: 'Connected',
    })),
    http.get(`${API_BASE_URL}/repositories/browse`, () => HttpResponse.json({ entries: [
      { type: 'folder', name: 'Layer1', path: 'Layer1', children: [
        { type: 'folder', name: 'Sample', path: 'Layer1/Sample', children: [
          { type: 'folder', name: 'Core', path: 'Layer1/Sample/Core', children: [
            { type: 'file', name: 'a.cpp', path: 'Layer1/Sample/Core/a.cpp' }] }] }] }] })),
    http.post(`${API_BASE_URL}/repositories/browse`, () => HttpResponse.json({ entries: [] })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/new']}>
        <NewProjectPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return calls
}

beforeAll(() => {
  // jsdom has no scrolling; the wizard scrolls to the top on every step.
  if (!Element.prototype.scrollTo) Element.prototype.scrollTo = () => {}
})
afterEach(() => { server.events.removeAllListeners('request:start') })

const settle = () => new Promise((r) => setTimeout(r, 1500))
const count = (calls: string[], what: string) => calls.filter((c) => c.endsWith(what)).length

// The whole wizard renders: its first render is slow on a loaded machine.
describe('Config import: a fixed number of requests', { timeout: 60_000 }, () => {
  it('reads the file once and then asks nothing more', async () => {
    const calls = setup()
    const input = await waitFor(() => {
      const el = document.querySelector('input[type="file"][accept=".json,.jsonc"]')
      expect(el).not.toBeNull()
      return el as HTMLInputElement
    })
    const file = new File([JSON.stringify({ project: { name: 'Brake ECU' } })], 'brake.json',
      { type: 'application/json' })
    fireEvent.change(input, { target: { files: [file] } })
    await waitFor(() => expect(count(calls, '/projects/config/preview')).toBe(1))
    const after = calls.length
    await settle()
    expect(calls.slice(after)).toEqual([])
  })

  it('Test Connection after an import: one connection test, one tree, one re-check, then quiet', async () => {
    const calls = setup()
    const input = await waitFor(() => {
      const el = document.querySelector('input[type="file"][accept=".json,.jsonc"]')
      expect(el).not.toBeNull()
      return el as HTMLInputElement
    })
    fireEvent.change(input, { target: { files: [new File(['{}'], 'brake.json')] } })
    await waitFor(() => expect(count(calls, '/projects/config/preview')).toBe(1))
    fireEvent.click(await screen.findByRole('button', { name: /Test Connection/i }))
    await waitFor(() => expect(count(calls, '/projects/config/preview')).toBe(2))
    const after = calls.length
    await settle()
    expect(calls.slice(after)).toEqual([])
    expect(count(calls, '/repositories/test-connection')).toBe(1)
    expect(count(calls, '/repositories/browse')).toBe(1)
  })
})
