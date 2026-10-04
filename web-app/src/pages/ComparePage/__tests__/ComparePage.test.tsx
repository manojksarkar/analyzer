import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import project from '../../../test/fixtures/captured/project.json'
import commits from '../../../test/fixtures/captured/commits.json'
import versionsFx from '../../../test/fixtures/captured/versions.json'
import documentsFx from '../../../test/fixtures/captured/documents.json'
import { ComparePage } from '..'
import { useUIStore } from '../../../store/ui'
import { compareVersions, olderVersions, versionRef } from '../helpers'
import type { Version } from '../../../types'

/* Compare names versions by id: two versions made on one commit are two versions (by commit the
   second found the first, and showed "No changes"). A failed read shows its error and Retry. The
   title line is the document's own (SWE.4's here), not always SWE.3's. */

// v1.2.0 and v1.1.0 made on the same commit.
const [v3, v2] = versionsFx.versions
const sameCommit = { versions: [v3, { ...v2, commit_sha: v3.commit_sha }] }
const swe4 = { ...documentsFx.documents[0], id: 'doc9', name: 'Brake', process: 'SWE.4', subtitle: 'Unit Test Specification', group: 'Brake' }

// An unchanged document of the current version (the list's Compare can name one).
const same = { ...documentsFx.documents[0], id: 'doc8', name: 'Pedal', process: 'SWE.3', subtitle: 'Detailed Design', group: 'Pedal' }

// A document of the version before the latest (a link from that version's documents).
const older = { ...documentsFx.documents[0], id: 'doc7', name: 'Gear', process: 'SWE.3', subtitle: 'Detailed Design', group: 'Gear', version_id: 'ver2' }

// The page's address, shown so a test can read what a pick wrote into it.
function Where() {
  return <output data-testid="where">{useLocation().search}</output>
}

function setup({ failCompare = false, path = '/projects/p1/compare', versions = sameCommit, holdVersions = false, removed = false, holdJob = false } = {}) {
  let release = () => {}
  const held = new Promise<void>((r) => { release = r })
  let releaseJob = () => {}
  const heldJob = new Promise<void>((r) => { releaseJob = r })
  const asked: string[] = []
  const details: string[] = []
  let failures = failCompare ? 1 : 0
  server.use(
    http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
    http.get(`${API_BASE_URL}/projects/p1/versions`, async () => {
      if (holdVersions) await held
      return HttpResponse.json(versions)
    }),
    http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
    http.get(`${API_BASE_URL}/projects/p1/jobs/current`, async () => {
      if (holdJob) await heldJob
      return HttpResponse.json({ job: null })
    }),
    http.get(`${API_BASE_URL}/projects/p1/documents`, ({ request }) => {
      const docs = new URL(request.url).searchParams.get('version_id') === 'ver2' ? [older] : [swe4, same]
      return HttpResponse.json({ documents: docs, pagination: { page: 1, per_page: 100, total: docs.length } })
    }),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc9`, () => HttpResponse.json({ document: swe4 })),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc8`, () => HttpResponse.json({ document: same })),
    http.get(`${API_BASE_URL}/projects/p1/documents/doc7`, () => HttpResponse.json({ document: older })),
    http.get(`${API_BASE_URL}/projects/p1/compare/documents`, ({ request }) => {
      const u = new URL(request.url)
      asked.push(`${u.searchParams.get('current')} vs ${u.searchParams.get('baseline')}`)
      if (failures > 0) {
        failures -= 1
        return HttpResponse.json({ detail: { code: 'INTERNAL', message: 'Compare crashed' } }, { status: 500 })
      }
      return HttpResponse.json({
        documents: [
          { document_id: 'doc9', name: 'Brake', process: 'SWE.4', diff_type: 'changed', sections_changed: [] },
          ...(removed ? [{ document_id: 'doc7', name: 'Gear', process: 'SWE.3', diff_type: 'removed', sections_changed: [] }] : []),
        ],
        summary: { added: 0, changed: 1, removed: removed ? 1 : 0, unchanged: 0 },
      })
    }),
    http.get(`${API_BASE_URL}/projects/p1/compare/documents/:docId`, ({ params }) => {
      details.push(String(params.docId))
      const name = params.docId === 'doc8' ? 'Pedal' : params.docId === 'doc7' ? 'Gear' : 'Brake'
      return HttpResponse.json({ mode: 'flat', document_name: name, sections: [] })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/projects/:projectId/compare" element={<><ComparePage /><Where /></>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  return { asked, details, release, releaseJob, user: userEvent.setup() }
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

/* #30: the documents list's Compare opens the document it names, changed or not, and the
   reference can be any older version. #45: a change is told by a sign and in words, not by its
   colour alone. */
describe('ComparePage: the linked document, the reference, the change marks', { timeout: 30_000 }, () => {
  it('?doc= opens that document even when it did not change, listed under All', async () => {
    const { details } = setup({ path: '/projects/p1/compare?doc=doc8' })
    expect((await screen.findAllByRole('heading', { name: 'Pedal' })).length).toBe(2)
    expect(details).toEqual(['doc8'])
    expect(screen.getByRole('button', { name: 'All' })).toHaveClass('bg-primary')
  })

  it('?doc= of a changed document opens it under Diff', async () => {
    const { details } = setup({ path: '/projects/p1/compare?doc=doc9' })
    expect((await screen.findAllByRole('heading', { name: 'Brake' })).length).toBe(2)
    expect(details).toEqual(['doc9'])
    expect(screen.getByRole('button', { name: 'Diff' })).toHaveClass('bg-primary')
  })

  it('the reference is the version before by default, and any older one can be picked', async () => {
    const { asked, user } = setup({ versions: versionsFx })
    const picker = await screen.findByRole('combobox', { name: 'Reference version' })
    expect(picker).toHaveValue('ver2')
    await waitFor(() => expect(asked).toEqual(['ver3 vs ver2']))
    await user.selectOptions(picker, 'ver1')
    await waitFor(() => expect(asked).toEqual(['ver3 vs ver2', 'ver3 vs ver1']))
    expect(screen.getByRole('combobox', { name: 'Reference version' })).toHaveValue('ver1')
  })

  it('with one older version the reference is shown, not offered', async () => {
    setup()
    expect((await screen.findAllByRole('heading', { name: 'Brake' })).length).toBe(2)
    expect(screen.queryByRole('combobox', { name: 'Reference version' })).not.toBeInTheDocument()
  })

  it('#16: says nothing about the comparison until the versions are read', async () => {
    const { release } = setup({ holdVersions: true })
    await new Promise((r) => setTimeout(r, 200))
    expect(screen.queryByText('Nothing to compare yet')).not.toBeInTheDocument()
    release()
    expect((await screen.findAllByRole('heading', { name: 'Brake' })).length).toBe(2)
  })

  it('a changed document says so with a sign and in words', async () => {
    setup()
    expect((await screen.findAllByRole('heading', { name: 'Brake' })).length).toBe(2)
    expect(screen.getByText('(changed)')).toHaveClass('sr-only')
    expect(screen.getByTitle('changed')).toHaveTextContent('~')
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

  it('the reference can be any older version, never the current one or a newer one', () => {
    const list = [v('ver3', 'abc'), v('ver2', 'abc'), v('ver1', 'def')]
    expect(compareVersions(list, list[0], 'ver1').baseline?.id).toBe('ver1')
    expect(compareVersions(list, list[1], 'ver3').baseline?.id).toBe('ver1')     // newer: the default
    expect(compareVersions(list, list[0], 'gone').baseline?.id).toBe('ver2')
    expect(olderVersions(list, list[1]).map((x) => x.id)).toEqual(['ver1'])
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

/* Smoke test: `/compare?doc=<id>` compared the latest version, not the document's own. */
describe('ComparePage opened on a document of an older version', { timeout: 30_000 }, () => {
  // Unmounted before the pick is cleared: a page still open would follow its document again.
  afterEach(() => { cleanup(); useUIStore.setState({ selectedRef: {} }) })

  it("compares the document's own version with the one before it, never the latest first", async () => {
    const { asked, details } = setup({ path: '/projects/p1/compare?doc=doc7', versions: versionsFx })
    expect((await screen.findAllByRole('heading', { name: 'Gear' })).length).toBe(2)
    expect(asked).toEqual(['ver2 vs ver1'])
    expect(details).toEqual(['doc7'])
    expect(useUIStore.getState().selectedRef.p1).toEqual({ type: 'version', id: 'ver2' })
  })

  it('reads nothing until the shown version is known: never the latest version first', async () => {
    const { asked, releaseJob } = setup({ path: '/projects/p1/compare?doc=doc7', versions: versionsFx, holdJob: true })
    await new Promise((r) => setTimeout(r, 300))
    expect(asked).toEqual([])
    releaseJob()
    expect((await screen.findAllByRole('heading', { name: 'Gear' })).length).toBe(2)
    expect(asked).toEqual(['ver2 vs ver1'])
  })
})

/* Review of 2026-10-05: a removed document is the reference's. Picked in the tree, its address
   named only it, and a reload followed it to the reference's version -- another comparison. */
describe('ComparePage: a removed document picked, then the page reloaded', { timeout: 30_000 }, () => {
  afterEach(() => { cleanup(); useUIStore.setState({ selectedRef: {} }) })

  it('the pick writes the reference into the address too', async () => {
    const { user } = setup({ versions: versionsFx, removed: true })
    await user.click(await screen.findByRole('button', { name: /Gear/ }))
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent('doc=doc7'))
    expect(screen.getByTestId('where')).toHaveTextContent('ref=ver2')
    expect(useUIStore.getState().selectedRef.p1).toBeUndefined()
  })

  it('that address compares the same two versions; it does not follow the document', async () => {
    const { asked, details } = setup({ path: '/projects/p1/compare?doc=doc7&ref=ver2', versions: versionsFx, removed: true })
    expect((await screen.findAllByRole('heading', { name: 'Gear' })).length).toBe(2)
    expect(asked).toEqual(['ver3 vs ver2'])
    expect(details).toEqual(['doc7'])
    expect(useUIStore.getState().selectedRef.p1).toBeUndefined()
  })
})
