import type { ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { liveSelection } from '../../lib/selection'
import { useUIStore } from '../../store/ui'
import project from '../../test/fixtures/captured/project.json'
import commits from '../../test/fixtures/captured/commits.json'
import versions from '../../test/fixtures/captured/versions.json'
import { useFollowDocumentVersion, useProjectViewState, useRefreshOnJobEnd } from '../useProjectViewState'
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
   project is open refreshes it, once. Review of cded9b4: what was seen is per project (a switch
   refreshed the next project); a run from the command line (`--detach`) ending refreshes too; and
   a job seen only once it was over (another job id) counts as one that ended. */
describe('useRefreshOnJobEnd', () => {
  const job = (status: string, id = 'job1') => ({
    id, status, phase: 4, phase_pct: 100, current_activity: '', activity_detail: '',
    elapsed_seconds: 60, eta_seconds: null, phases: [],
    commit_sha: 'b2e8d45', branch: 'main', version_id: 'ver3', version_tag: 'v3', mode: 'auto',
    started_at: '2026-10-01T09:00:00Z', completed_at: null, error_message: null,
  })
  const run = (command: string) => ({
    version_id: 'ver3', version_tag: 'v3', command, alive: true, stopped: false, outcome: 'running',
    started_at: '2026-10-01T09:00:00Z', stage: 'flowcharts', done: 1, total: 4,
  })

  function mount(firstStatus: string | null, firstRuns: object[] = []) {
    const state = { status: firstStatus, jobId: 'job1', runs: firstRuns, projectReads: 0, runsReads: 0 }
    server.use(
      http.get(`${API_BASE_URL}/projects/p1`, () => { state.projectReads++; return HttpResponse.json(project) }),
      http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
      http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
      http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () =>
        HttpResponse.json({ job: state.status ? job(state.status, state.jobId) : null })),
      http.get(`${API_BASE_URL}/projects/p1/runs`, () => { state.runsReads++; return HttpResponse.json({ runs: state.runs }) }),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    // The layout (refresh + view state) and a page (view state), as the app mounts them.
    const useLayout = () => { useRefreshOnJobEnd('p1'); return useProjectViewState('p1') }
    const layout = renderHook(useLayout, { wrapper })
    return {
      state, client, layout,
      mountPage: () => renderHook(() => useProjectViewState('p1'), { wrapper }),
      mountLayout: () => renderHook(useLayout, { wrapper }),
    }
  }
  const settle = () => new Promise((r) => setTimeout(r, 100))
  const readJob = (client: QueryClient) => client.invalidateQueries({ queryKey: projectKeys.job('p1'), exact: true })
  const readRuns = (client: QueryClient) => client.invalidateQueries({ queryKey: projectKeys.runs('p1'), exact: true })

  it('reads nothing again when the last run had already ended', async () => {
    const { state, layout, mountPage, mountLayout } = mount('complete')
    await waitFor(() => expect(layout.result.current.isLoading).toBe(false))
    await waitFor(() => expect(state.runsReads).toBe(1))
    const page = mountPage()                                   // a second page visit
    await waitFor(() => expect(page.result.current.isLoading).toBe(false))
    // The layout mounted again (back into the project from the projects list), as the app does.
    layout.unmount()
    const again = mountLayout()
    await waitFor(() => expect(again.result.current.isLoading).toBe(false))
    await settle()
    expect(state.projectReads).toBe(1)
  })

  it('reads the project again once when a run ends while it is open', async () => {
    // The web run is among the runs too: its drop there is read by the same refresh, not a second.
    const { state, client, layout } = mount('running', [run('web run')])
    await waitFor(() => expect(layout.result.current.pageState).toBe('running'))
    await waitFor(() => expect(state.runsReads).toBe(1))
    expect(state.projectReads).toBe(1)
    state.status = 'complete'
    state.runs = []
    await readJob(client)
    await waitFor(() => expect(state.projectReads).toBe(2))
    // The runs (the Overview's other-runs cards) are among what is read again: no 15 s of a
    // "Running …" card for the run that just ended.
    await waitFor(() => expect(state.runsReads).toBe(2))
    await settle()
    expect(state.projectReads).toBe(2)
  })

  it('a run from the command line ending reads the project again, once', async () => {
    const { state, client, layout } = mount(null, [run('export')])
    await waitFor(() => expect(layout.result.current.isLoading).toBe(false))
    await waitFor(() => expect(state.runsReads).toBe(1))
    state.runs = []
    await readRuns(client)                                     // the runs' own poll
    await waitFor(() => expect(state.projectReads).toBe(2))
    await settle()
    expect(state.projectReads).toBe(2)
  })

  it('a job seen only once it was over (another id) is a run that ended', async () => {
    const { state, client, layout } = mount('complete')
    await waitFor(() => expect(layout.result.current.isLoading).toBe(false))
    state.jobId = 'job2'                                       // started and ended between two reads
    await readJob(client)
    await waitFor(() => expect(state.projectReads).toBe(2))
  })

  it('switching projects does not read the next one again', async () => {
    server.use(
      http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: job('running') })),
      http.get(`${API_BASE_URL}/projects/p1/runs`, () => HttpResponse.json({ runs: [] })),
      http.get(`${API_BASE_URL}/projects/p2/jobs/current`, () => HttpResponse.json({ job: job('complete', 'job9') })),
      http.get(`${API_BASE_URL}/projects/p2/runs`, () => HttpResponse.json({ runs: [] })),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 60_000 } } })
    // p2 was visited before: its job is in the cache, so the switch shows it at once.
    client.setQueryData(projectKeys.job('p2'), { id: 'job9', status: 'complete' })
    const spy = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const hook = renderHook(({ pid }) => useRefreshOnJobEnd(pid), { wrapper, initialProps: { pid: 'p1' } })
    await waitFor(() => expect(client.getQueryData(projectKeys.job('p1'))).toMatchObject({ status: 'running' }))
    hook.rerender({ pid: 'p2' })
    await settle()
    expect(spy).not.toHaveBeenCalledWith({ queryKey: projectKeys.detail('p2') })
  })
})

/* Smoke test: a document opened by its address showed the Subbar chip and status of the latest
   version, and Compare compared the latest. The pick follows the document's version. */
describe('useFollowDocumentVersion', () => {
  // Unmounted before the pick is cleared: a page still open would follow its document again.
  afterEach(() => { cleanup(); useUIStore.setState({ selectedRef: {} }) })

  function mount(doc: { id: string; versionId: string }) {
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
    return renderHook(({ d }) => ({ follow: useFollowDocumentVersion('p1', d), view: useProjectViewState('p1') }),
      { wrapper, initialProps: { d: doc } })
  }
  const settle = () => new Promise((r) => setTimeout(r, 50))

  it("picks the document's version when the shown one is another", async () => {
    const { result } = mount({ id: 'd2', versionId: 'ver2' })
    await waitFor(() => expect(result.current.view.viewVersionId).toBe('ver2'))
    expect(useUIStore.getState().selectedRef.p1).toEqual({ type: 'version', id: 'ver2' })
    expect(result.current.follow.following).toBe(false)
  })

  it('picks nothing when the shown version is already the document’s (the latest)', async () => {
    const { result } = mount({ id: 'd3', versionId: 'ver3' })
    await waitFor(() => expect(result.current.view.isLoading).toBe(false))
    await settle()
    expect(useUIStore.getState().selectedRef.p1).toBeUndefined()
    expect(result.current.follow.following).toBe(false)
  })

  it('a pick made afterwards stands; another document opened follows again', async () => {
    const { result, rerender } = mount({ id: 'd2', versionId: 'ver2' })
    await waitFor(() => expect(result.current.view.viewVersionId).toBe('ver2'))
    act(() => useUIStore.getState().setSelectedRef('p1', { type: 'version', id: 'ver1' }))
    await settle()
    expect(result.current.view.viewVersionId).toBe('ver1')
    rerender({ d: { id: 'd9', versionId: 'ver2' } })
    await waitFor(() => expect(result.current.view.viewVersionId).toBe('ver2'))
  })
})
