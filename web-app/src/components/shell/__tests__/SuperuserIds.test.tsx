import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { useAuthStore } from '../../../store/auth'
import { useUIStore } from '../../../store/ui'
import versions from '../../../test/fixtures/captured/versions.json'
import commits from '../../../test/fixtures/captured/commits.json'
import { Subbar } from '../Subbar'
import type { Version } from '../../../types'

/* A superuser sees the project's and the version's ids beside the version chip -- the ones
   analyzer.py and the logs name -- and a click copies one. Nobody else sees them. */

function mount(superuser: boolean) {
  useAuthStore.setState({ user: { id: 'u1', name: 'Admin', email: 'admin@company.com', initials: 'AD', isSuperuser: superuser } })
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/projects/p1/overview']}>
        <Routes>
          <Route path="/projects/:projectId/overview"
            element={<Subbar projectName="Sample" selectedVersion={{ id: 'ver3', tag: 'v1.2', sha: 'abc', shortSha: 'abc' } as Version} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return userEvent.setup()
}

describe('Superuser ids in the Subbar', { timeout: 20_000 }, () => {
  afterEach(() => {
    useAuthStore.setState({ user: null })
    useUIStore.setState({ selectedRef: {} })
    vi.unstubAllGlobals()
  })

  it("shows the project's and the shown version's ids, and follows the pick", async () => {
    mount(true)
    const ids = await screen.findByLabelText('Ids')
    expect(within(ids).getByRole('button', { name: 'p1' })).toBeInTheDocument()
    expect(within(ids).getByRole('button', { name: 'ver3' })).toBeInTheDocument()
    act(() => useUIStore.getState().setSelectedRef('p1', { type: 'version', id: 'ver2' }))
    await waitFor(() => expect(within(ids).getByRole('button', { name: 'ver2' })).toBeInTheDocument())
  })

  it('a click copies the id', async () => {
    const user = mount(true)                      // user-event puts its own clipboard in: stub after it
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } })
    vi.stubGlobal('isSecureContext', true)
    await user.click(within(await screen.findByLabelText('Ids')).getByRole('button', { name: 'ver3' }))
    expect(writeText).toHaveBeenCalledWith('ver3')
  })

  it('nobody else sees them', async () => {
    mount(false)
    await screen.findByText('Sample')
    expect(screen.queryByLabelText('Ids')).not.toBeInTheDocument()
  })
})
