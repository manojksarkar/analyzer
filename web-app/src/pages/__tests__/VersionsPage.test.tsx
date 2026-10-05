import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import project from '../../test/fixtures/captured/project.json'
import commits from '../../test/fixtures/captured/commits.json'
import versionsFx from '../../test/fixtures/captured/versions.json'
import { VersionsPage } from '../VersionsPage'

/* Smoke test: a version's meta line ("sha · N docs · date · how made") left a stray "·" at the
   end of the line when "how made" wrapped onto the next one. Each "·" goes with the item after
   it, so it wraps with that item. */

const [v3, ...rest] = versionsFx.versions
const made = { ...v3, run: { made_by: 'web', scope: { type: 'component', names: ['Layer1.Math'] }, doc_type: 'all', model_only: false } }

function setup() {
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json({ versions: [made, ...rest] })),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/versions']}>
        <Routes>
          <Route path="/projects/:projectId/versions" element={<VersionsPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('VersionsPage: a version row', { timeout: 30_000 }, () => {
  it('keeps each "·" with the item after it, so a wrapped line ends without one', async () => {
    setup()
    const how = await screen.findByTitle('How this version was made')
    expect(how).toHaveTextContent('Web run · component Layer1.Math · SWE.3 + SWE.4')
    // The separator and "how made" wrap as one item of the line.
    const item = how.parentElement as HTMLElement
    expect(item.firstElementChild).toHaveTextContent(/^·$/)
    expect(item.firstElementChild).toHaveAttribute('aria-hidden')
    // No separator stands alone on the line: each one leads an item.
    const line = item.parentElement as HTMLElement
    for (const child of Array.from(line.children)) expect(child.textContent?.trim()).not.toBe('·')
  })
})
