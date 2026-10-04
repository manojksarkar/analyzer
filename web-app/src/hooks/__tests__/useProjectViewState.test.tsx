import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { liveSelection } from '../../lib/selection'
import { useUIStore } from '../../store/ui'
import project from '../../test/fixtures/captured/project.json'
import commits from '../../test/fixtures/captured/commits.json'
import versions from '../../test/fixtures/captured/versions.json'
import { useProjectViewState, useRefreshOnJobEnd } from '../useProjectViewState'
import { projectKeys } from '../useProjects'
import type { Version } from '../../types'

/* A Subbar pick naming a version that is gone — a cancelled run's draft — is no pick: the default
   version shows. It resolved to no version, and the pages read every version's documents. */

const v = (id: string) => ({ id }) as Version

describe('liveSelection', () => {
  it('drops a pick of a version that is not there, once the versions are known', () => {
    const gone = { type: 'version', id: 'verGone' } as const
    expect(liveSelection(gone, [v('ver3'), v('ver2')])).toBeUndefined()
    expect(liveSelection(gone, undefined)).toBe(gone)
  })

  it('keeps a pick of a version that is there, and any commit pick', () => {
    const there = { type: 'version', id: 'ver2' } as const
    const commit = { type: 'commit', sha: 'abc1234' } as const
    expect(liveSelection(there, [v('ver3'), v('ver2')])).toBe(there)
    expect(liveSelection(commit, [v('ver3')])).toBe(commit)
    expect(liveSelection(undefined, [v('ver3')])).toBeUndefined()
  })
})

describe('useProjectViewState', () => {
  afterEach(() => useUIStore.setState({ selectedRef: {} }))

  function mount() {
    server.use(
      http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
      http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
      http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
      http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    return renderHook(() => useProjectViewState('p1'), { wrapper })
  }

  it('shows the default version when the picked one is gone', async () => {
    useUIStore.getState().setSelectedRef('p1', { type: 'version', id: 'verDeletedDraft' })
    const { result } = mount()
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.viewVersionId).toBe('ver3')
  })

  it('shows the picked version while it is there', async () => {
    useUIStore.getState().setSelectedRef('p1', { type: 'version', id: 'ver2' })
    const { result } = mount()
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.viewVersionId).toBe('ver2')
  })
})

/* #29: every visit to a project page read the whole project again — the last run being
   "complete", the job-end refresh fired on every mount. Now only a run that ends while the
   project is open refreshes it, once. */
describe('useRefreshOnJobEnd', () => {
  const job = (status: string) => ({
    id: 'job1', status, phase: 4, phase_pct: 100, current_activity: '', activity_detail: '',
    elapsed_seconds: 60, eta_seconds: null, phases: [],
    commit_sha: 'b2e8d45', branch: 'main', version_id: 'ver3', version_tag: 'v3', mode: 'auto',
    started_at: '2026-10-01T09:00:00Z', completed_at: null, error_message: null,
  })

  function mount(firstStatus: string) {
    const state = { status: firstStatus, projectReads: 0 }
    server.use(
      http.get(`${API_BASE_URL}/projects/p1`, () => { state.projectReads++; return HttpResponse.json(project) }),
      http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
      http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
      http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: job(state.status) })),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    // The layout (refresh + view state) and a page (view state), as the app mounts them.
    const useLayout = () => { useRefreshOnJobEnd('p1'); return useProjectViewState('p1') }
    const layout = renderHook(useLayout, { wrapper })
    return { state, client, layout, mountPage: () => renderHook(() => useProjectViewState('p1'), { wrapper }) }
  }
  const settle = () => new Promise((r) => setTimeout(r, 100))

  it('reads nothing again when the last run had already ended', async () => {
    const { state, layout, mountPage } = mount('complete')
    await waitFor(() => expect(layout.result.current.isLoading).toBe(false))
    const page = mountPage()                                   // a second page visit
    await waitFor(() => expect(page.result.current.isLoading).toBe(false))
    await settle()
    expect(state.projectReads).toBe(1)
  })

  it('reads the project again once when a run ends while it is open', async () => {
    const { state, client, layout } = mount('running')
    await waitFor(() => expect(layout.result.current.pageState).toBe('running'))
    expect(state.projectReads).toBe(1)
    // The runs (the Overview's other-runs cards) are among what is read again: no 15 s of a
    // "Running …" card for the run that just ended.
    client.setQueryData(projectKeys.runs('p1'), [])
    state.status = 'complete'
    await client.invalidateQueries({ queryKey: projectKeys.job('p1'), exact: true })
    await waitFor(() => expect(state.projectReads).toBe(2))
    expect(client.getQueryState(projectKeys.runs('p1'))?.isInvalidated).toBe(true)
    await settle()
    expect(state.projectReads).toBe(2)
  })
})
