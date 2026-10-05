import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { useToastStore } from '../../components/ui/Toast'
import { cancelJobAndWait, useCancelJob } from '../useJobs'
import { projectKeys } from '../useProjects'

/* Cancelling a version's own run: the server deletes its draft version a moment after the cancel
   answers (seconds for a big draft), and the job stops naming it BEFORE the version is gone. The
   UI waits until the version itself is gone before it refetches, or the refetch brings the
   deleted draft back as the project's newest version. */

const apiJob = (over: Record<string, unknown> = {}) => ({
  id: 'job9', status: 'cancelled', phase: 3, phase_pct: 40, current_activity: '', activity_detail: '',
  elapsed_seconds: 60, eta_seconds: null, phases: [], commit_sha: 'abc1234', branch: 'main',
  version_id: 'ver9', version_tag: 'v2', mode: 'auto',
  started_at: '2026-10-01T09:00:00Z', completed_at: '2026-10-01T09:01:00Z', error_message: null,
  ...over,
})

const apiVersion = {
  id: 'ver9', tag: 'v2', commit_sha: 'abc1234', branch: 'main', description: '', status: 'draft',
  docs_count: 0, created_by: 'u1', created_at: '2026-10-01T09:00:00+00:00',
}

/** The cancel answers `cancel` (or a 409 when it is a number); each later read of the job answers
 *  the next of `reads`; the version is there for the first `versionReads` reads, then 404. */
function serve(cancel: object | 409, reads: object[] = [], versionReads = 0) {
  const calls = { cancel: 0, get: 0, version: 0 }
  server.use(
    http.post(`${API_BASE_URL}/projects/p1/jobs/job9/cancel`, () => {
      calls.cancel++
      if (cancel === 409) {
        // The API's shape (api/services/errors.py `conflict`): FastAPI's `detail`.
        return HttpResponse.json(
          { detail: { code: 'JOB_FINISHED', message: 'Job job9 has already ended.', status: 409 } },
          { status: 409 })
      }
      return HttpResponse.json({ job: cancel })
    }),
    http.get(`${API_BASE_URL}/projects/p1/jobs/job9`, () => {
      const job = reads[Math.min(calls.get, reads.length - 1)]
      calls.get++
      return HttpResponse.json({ job })
    }),
    http.get(`${API_BASE_URL}/projects/p1/versions/ver9`, () => {
      calls.version++
      return calls.version <= versionReads
        ? HttpResponse.json({ version: apiVersion })
        : HttpResponse.json({ detail: { code: 'NOT_FOUND', message: 'Version not found', status: 404 } }, { status: 404 })
    }),
  )
  return calls
}

describe('cancelJobAndWait', () => {
  it("waits until the run's draft version is gone, not until the job stops naming it", async () => {
    // The job is detached at once; the version answers twice more before its delete lands.
    const calls = serve(apiJob(), [apiJob({ version_id: null })], 2)
    const job = await cancelJobAndWait('p1', 'job9', 1)
    expect(job.status).toBe('cancelled')
    expect(calls).toEqual({ cancel: 1, get: 3, version: 3 })
  })

  it('does not wait when the cancel already deleted the draft', async () => {
    const calls = serve(apiJob({ version_id: null }))
    expect((await cancelJobAndWait('p1', 'job9', 1)).status).toBe('cancelled')
    expect(calls.get + calls.version).toBe(0)
  })

  it('does not wait for a job that adds documents: its version stays', async () => {
    const calls = serve(apiJob({ mode: 'export', version_id: 'ver1' }))
    expect((await cancelJobAndWait('p1', 'job9', 1)).versionId).toBe('ver1')
    expect(calls.get + calls.version).toBe(0)
  })

  it('gives up waiting when the job cannot be read', async () => {
    serve(apiJob())
    server.use(http.get(`${API_BASE_URL}/projects/p1/jobs/job9`, () => new HttpResponse(null, { status: 500 })))
    expect((await cancelJobAndWait('p1', 'job9', 1)).versionId).toBe('ver9')
  })

  it('gives up waiting when the version read fails with anything but 404', async () => {
    const calls = serve(apiJob(), [apiJob()])
    server.use(http.get(`${API_BASE_URL}/projects/p1/versions/ver9`, () => new HttpResponse(null, { status: 500 })))
    expect((await cancelJobAndWait('p1', 'job9', 1)).versionId).toBe('ver9')
    expect(calls.get).toBe(1)
  })

  it('stops waiting at once when the run had already finished: its version stays', async () => {
    const calls = serve(apiJob(), [apiJob({ status: 'complete' })], 99)
    const job = await cancelJobAndWait('p1', 'job9', 1)
    expect(job.status).toBe('complete')
    expect(job.versionId).toBe('ver9')
    expect(calls).toEqual({ cancel: 1, get: 1, version: 0 })
  })

  it('a cancel refused because the run had finished is the same late cancel', async () => {
    const calls = serve(409, [apiJob({ status: 'complete' })], 99)
    expect((await cancelJobAndWait('p1', 'job9', 1)).status).toBe('complete')
    expect(calls.version).toBe(0)
  })

  it('a cancel refused because someone else cancelled first is a cancel: it waits for the version', async () => {
    // Two admins, or Stop pressed in two places: the job is already `cancelled`, its draft not gone yet.
    const calls = serve(409, [apiJob()], 1)
    const job = await cancelJobAndWait('p1', 'job9', 1)
    expect(job.status).toBe('cancelled')
    expect(calls).toEqual({ cancel: 1, get: 3, version: 2 })
  })

  it('a cancel refused for a run that ended otherwise stays an error', async () => {
    serve(409, [apiJob({ status: 'failed' })])
    await expect(cancelJobAndWait('p1', 'job9', 1)).rejects.toThrow('already ended')
  })
})

describe('useCancelJob', () => {
  afterEach(() => useToastStore.setState({ toasts: [] }))

  function mount() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(projectKeys.versions('p1'), [{ id: 'ver9', status: 'draft' }])
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useCancelJob('p1'), { wrapper })
    return { client, result }
  }

  it("refetches the project's versions once the draft is gone", async () => {
    serve(apiJob({ version_id: null }))
    const { client, result } = mount()
    act(() => result.current.mutate('job9'))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(client.getQueryState(projectKeys.versions('p1'))?.isInvalidated).toBe(true)
    expect(useToastStore.getState().toasts.map((t) => t.title)).toEqual(['Job cancelled'])
  })

  it('says so when the run had already finished, instead of "Job cancelled"', async () => {
    serve(apiJob(), [apiJob({ status: 'complete' })])
    const { result } = mount()
    act(() => result.current.mutate('job9'))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const [t] = useToastStore.getState().toasts
    expect(t.title).toBe('The run had already finished')
    expect(t.description).toBe('Its version was kept.')
  })

  it('a job someone else cancelled first says "Job cancelled", not "Cancel failed"', async () => {
    serve(409, [apiJob()])
    const { result } = mount()
    act(() => result.current.mutate('job9'))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(useToastStore.getState().toasts.map((t) => t.title)).toEqual(['Job cancelled'])
  })
})
