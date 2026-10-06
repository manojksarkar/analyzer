import { createElement, type ReactNode } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { useToastStore } from '../../components/ui/Toast'
import { useWordFilesStore } from '../../store/wordFiles'
import { notifKeys } from '../useNotifications'
import { projectKeys } from '../useProjects'
import { readinessPollMs, useUpdateWordFiles, useWordFilesWatcher } from '../useWordFiles'
import type { ExportReadiness } from '../../types'

/* The end of an update (WORD_FILE_UPDATES W6): a toast — written to anyone watching, failed only
   to its starter —, the bell read again, the download that waited for it. A cancelled update
   tells nobody. */

const BRAKE = 'Layer1.Brake-Controller'
const words = { versionTag: 'v1.2.0', nameOf: (c: string) => (c === BRAKE ? 'Brake Controller' : c) }
const r9 = (status: string, over: Partial<NonNullable<ExportReadiness['reexport']>> = {}): ExportReadiness => ({
  stale: false, explanation: null, overrideCount: 0, pendingRenders: 0, failedRenders: 0, outOfDate: [], writer: null,
  reexport: {
    jobId: 'job1', status, startedAt: null, completedAt: null, errorMessage: null, scope: 'out_of_date', reason: 'update',
    components: [BRAKE], componentsDone: 0, startedBy: { userId: 'u1', name: 'Admin', initials: 'AD' }, ...over,
  },
})

function watch(first: ExportReadiness, meId = 'u1') {
  const client = new QueryClient()
  const spy = vi.spyOn(client, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
  const hook = renderHook(({ r }) => useWordFilesWatcher('p1', 'v1', r, { meId, words }), { wrapper, initialProps: { r: first } })
  return { ...hook, spy }
}
const toasts = () => useToastStore.getState().toasts.map((t) => [t.variant, t.title, t.description])

afterEach(() => {
  useToastStore.setState({ toasts: [] })
  useWordFilesStore.setState({ pending: {}, justUpdated: {} })
})

describe('useWordFilesWatcher', () => {
  it('written: says so, reads the pages, the review reads and the bell again, and marks what it wrote', () => {
    const { rerender, spy } = watch(r9('running'))
    expect(toasts()).toEqual([])
    rerender({ r: r9('complete') })
    expect(toasts()).toEqual([['success', 'Word files updated.', 'Brake Controller']])
    expect(spy).toHaveBeenCalledWith({ queryKey: notifKeys.all })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['projects', 'p1', 'documents'] })
    expect(useWordFilesStore.getState().justUpdated.v1).toEqual([BRAKE])
  })

  it('a rebuild: Word files rebuilt, with the version', () => {
    const { rerender } = watch(r9('running', { scope: 'all' }))
    rerender({ r: r9('complete', { scope: 'all' }) })
    expect(toasts()).toEqual([['success', 'Word files rebuilt.', 'v1.2.0']])
  })

  it('failed: its starter is told why; anyone else is not', () => {
    const failed = r9('failed', { errorMessage: 'flowchart pictures could not be drawn' })
    const mine = watch(r9('running'))
    mine.rerender({ r: failed })
    expect(toasts()).toEqual([['error', 'Update failed.', 'Flowchart pictures could not be drawn.']])
    useToastStore.setState({ toasts: [] })
    const other = watch(r9('running'), 'u9')
    other.rerender({ r: failed })
    expect(toasts()).toEqual([])
  })

  it('cancelled: tells nobody', () => {
    const { rerender } = watch(r9('running'))
    rerender({ r: r9('cancelled') })
    expect(toasts()).toEqual([])
  })

  it('a download that waited for the update goes when its own job is written', async () => {
    const { downloads, jobs } = serveDownloads()
    jobs.job1 = 'running'
    useWordFilesStore.getState().addPending('job1', { projectId: 'p1', docId: 'doc1', fileName: 'b.docx', components: [BRAKE] })
    watch(r9('running'))
    await new Promise((r) => setTimeout(r, 50))
    expect(downloads()).toBe(0)
    jobs.job1 = 'complete'
    await waitFor(() => expect(downloads()).toBe(1), { timeout: 6000 })
    expect(useWordFilesStore.getState().pending.job1).toBeUndefined()
  })

  it('4: an update that ended between two reads (R9 already names the next) is still said, by its own job', async () => {
    const { jobs } = serveDownloads()
    jobs.job1 = 'complete'
    const { rerender, spy } = watch(r9('running'))
    // Job 1 ended and job 2 started before R9 was read again.
    rerender({ r: r9('running', { jobId: 'job2', components: ['Layer1.Other'] }) })
    await waitFor(() => expect(toasts()).toEqual([['success', 'Word files updated.', 'Brake Controller']]))
    expect(spy).toHaveBeenCalledWith({ queryKey: notifKeys.all })
  })

  it('4: a download that waited for that update goes too — it follows its own job, not R9', async () => {
    const { downloads, jobs } = serveDownloads()
    jobs.job1 = 'complete'
    useWordFilesStore.getState().addPending('job1', { projectId: 'p1', docId: 'doc1', fileName: 'b.docx', components: [BRAKE] })
    watch(r9('running', { jobId: 'job2', components: ['Layer1.Other'] }))
    await waitFor(() => expect(downloads()).toBe(1))
  })

  it('partly failed: one toast for the written files, one (to its starter) for the failed ones', () => {
    const { rerender } = watch(r9('running', { components: [BRAKE, 'Layer1.HVAC'] }))
    rerender({ r: r9('complete', { components: [BRAKE, 'Layer1.HVAC'], componentsFailed: ['Layer1.HVAC'],
      errorMessage: 'a download held the file' }) })
    expect(toasts()).toEqual([
      ['success', 'Word files updated.', 'Brake Controller'],
      ['error', 'Update failed.', 'Layer1.HVAC — A download held the file.'],
    ])
    // "Word files updated" only where they were.
    expect(useWordFilesStore.getState().justUpdated.v1).toEqual([BRAKE])
  })

  it('partly failed: a download of a component that failed does not go (its file was not written)', async () => {
    const { downloads, jobs } = serveDownloads()
    jobs.job1 = 'complete'
    useWordFilesStore.getState().addPending('job1', { projectId: 'p1', docId: 'doc1', fileName: 'b.docx', components: [BRAKE] })
    watch(r9('complete', { componentsFailed: [BRAKE] }))
    await waitFor(() => expect(useWordFilesStore.getState().pending.job1).toBeUndefined())
    await new Promise((r) => setTimeout(r, 50))
    expect(downloads()).toBe(0)
  })
})

/** The download route and each job's state (`GET /jobs/{id}`), as the tests set them. */
function serveDownloads() {
  URL.createObjectURL = vi.fn(() => 'blob:x')
  URL.revokeObjectURL = vi.fn()
  let n = 0
  const jobs: Record<string, string> = {}
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/documents/doc1/download`, () => {
      n += 1
      return new HttpResponse(new Blob(['docx']), { headers: { 'Content-Disposition': 'attachment; filename="b.docx"' } })
    }),
    http.get(`${API_BASE_URL}/projects/p1/jobs/:jobId`, ({ params }) => HttpResponse.json({ job: {
      id: params.jobId, status: jobs[String(params.jobId)] ?? 'running', phase: 4, phase_pct: 100, current_activity: '',
      activity_detail: '', elapsed_seconds: 1, eta_seconds: null, phases: [], commit_sha: 'abc1234', branch: 'main',
      version_id: 'v1', mode: 'reexport', started_at: null, completed_at: null, error_message: null,
    } })),
  )
  return { downloads: () => n, jobs }
}

describe('useUpdateWordFiles', () => {
  it('an update reads R9 (the version’s and each document’s) and the project’s runs again', async () => {
    server.use(http.post(`${API_BASE_URL}/projects/p1/versions/v1/reexport`, () => HttpResponse.json(
      { job_id: 'j1', status: 'queued', version_id: 'v1', scope: 'out_of_date', components: [BRAKE], joined: false }, { status: 202 })))
    const client = new QueryClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
    const { result } = renderHook(() => useUpdateWordFiles('p1', 'v1', words), { wrapper })
    await act(async () => { await result.current.mutateAsync({ request: { scope: 'out_of_date', components: [BRAKE] } }) })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.exportReadiness('p1', 'v1') })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.runs('p1') })
  })

  it('joined a running update that covers it: no second job, nothing said', async () => {
    server.use(http.post(`${API_BASE_URL}/projects/p1/versions/v1/reexport`, () => HttpResponse.json(
      { job_id: 'j0', status: 'running', version_id: 'v1', scope: 'out_of_date', components: [BRAKE], joined: true })))
    const client = new QueryClient()
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
    const { result } = renderHook(() => useUpdateWordFiles('p1', 'v1', words), { wrapper })
    await act(async () => {
      await result.current.mutateAsync({ request: { scope: 'out_of_date' }, download: { docId: 'doc1', fileName: 'b.docx' } })
    })
    // The download waits for the job it joined.
    expect(useWordFilesStore.getState().pending.j0?.[0]).toMatchObject({ docId: 'doc1' })
    expect(toasts()).toEqual([])
  })
})

describe('readinessPollMs', () => {
  it('every few seconds while an update writes, slowly while another run holds the version, else not', () => {
    expect(readinessPollMs(r9('running'))).toBe(2500)
    expect(readinessPollMs(r9('complete'))).toBe(false)
    expect(readinessPollMs({ ...r9('complete'), writer: {
      kind: 'generation', jobId: 'j', command: null, since: null, components: null, componentsDone: null,
      componentsTotal: null, startedBy: null,
    } })).toBe(15_000)
    expect(readinessPollMs(undefined)).toBe(false)
  })
})
