import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import versionsFx from '../../../test/fixtures/captured/versions.json'
import documentsFx from '../../../test/fixtures/captured/documents.json'
import { ComparePage } from '..'
import { compareVersions, versionRef } from '../helpers'
import type { Version } from '../../../types'

/* Compare names versions by id: two versions made on one commit are two versions (by commit the
   second found the first, and showed "No changes"). A failed read shows its error and Retry. The
   title line is the document's own (SWE.4's here), not always SWE.3's. */

// v1.2.0 and v1.1.0 made on the same commit.
const [v3, v2] = versionsFx.versions
const sameCommit = { versions: [v3, { ...v2, commit_sha: v3.commit_sha }] }
const swe4 = { ...documentsFx.documents[0], id: 'doc9', name: 'Brake', process: 'SWE.4', subtitle: 'Unit Test Specification', group: 'Brake' }

function setup({ failCompare = false } = {}) {
  const asked: string[] = []
  let failures = failCompare ? 1 : 0
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(sameCommit)),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    http.get(`${API_BASE_URL}/projects/p1/documents`, () =>
      HttpResponse.json({ documents: [swe4], pagination: { page: 1, per_page: 100, total: 1 } })),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc9`, () => HttpResponse.json({ document: swe4 })),
    http.get(`${API_BASE_URL}/projects/p1/compare/documents`, ({ request }) => {
      const u = new URL(request.url)
      asked.push(`${u.searchParams.get('current')} vs ${u.searchParams.get('baseline')}`)
      if (failures > 0) {
        failures -= 1
        return HttpResponse.json({ detail: { code: 'INTERNAL', message: 'Compare crashed' } }, { status: 500 })
      }
      return HttpResponse.json({
        documents: [{ document_id: 'doc9', name: 'Brake', process: 'SWE.4', diff_type: 'changed', sections_changed: [] }],
        summary: { added: 0, changed: 1, removed: 0, unchanged: 0 },
      })
    }),
    http.get(`${API_BASE_URL}/projects/p1/compare/documents/doc9`, () =>
      HttpResponse.json({ mode: 'flat', document_name: 'Brake', sections: [] })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/projects/p1/compare']}>
        <Routes>
          <Route path="/projects/:projectId/compare" element={<ComparePage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { asked, user: userEvent.setup() }
}

describe('ComparePage', { timeout: 30_000 }, () => {
  it('compares two versions of one commit by their ids, under the document’s own title', async () => {
    const { asked } = setup()
    expect((await screen.findAllByRole('heading', { name: 'Brake' })).length).toBe(2)
    expect(asked).toEqual(['ver3 vs ver2'])
    expect(screen.getAllByText('Software Unit Test Specification')).toHaveLength(2)
    expect(screen.queryByText('Software Detailed Design Specification')).not.toBeInTheDocument()
  })

  it('a failed read says so, with Retry, not "No changes"', async () => {
    const { asked, user } = setup({ failCompare: true })
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Could not load the comparison')
    expect(alert).toHaveTextContent('Compare crashed')
    expect(screen.queryByText(/No changes/)).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /Retry/ }))
    expect((await screen.findAllByRole('heading', { name: 'Brake' })).length).toBe(2)
    await waitFor(() => expect(asked).toEqual(['ver3 vs ver2', 'ver3 vs ver2']))
  })
})

describe('compareVersions', () => {
  const v = (id: string, sha: string) => ({ id, sha, tag: id }) as Version

  it('the reference is the version before the current one, found by id', () => {
    const list = [v('ver3', 'abc'), v('ver2', 'abc'), v('ver1', 'def')]
    expect(compareVersions(list, list[0]).baseline?.id).toBe('ver2')
    expect(compareVersions(list, list[1]).baseline?.id).toBe('ver1')
    expect(compareVersions(list, list[2]).baseline).toBeUndefined()
  })

  it('no current version (a commit with no run): nothing to compare', () => {
    expect(compareVersions([v('ver1', 'abc')], undefined)).toEqual({ current: undefined })
  })

  it('a version is named by its id; one without (an older API) by its commit', () => {
    expect(versionRef(v('ver3', 'abc'))).toBe('ver3')
    expect(versionRef({ sha: 'abc' } as Version)).toBe('abc')
    expect(versionRef(undefined)).toBeUndefined()
  })
})
