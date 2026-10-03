import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { cancelJobAndWait, useCancelJob } from '../useJobs'
import { projectKeys } from '../useProjects'

/* Cancelling a version's own run: the server deletes its draft version a moment after the cancel
   answers, and the job stops naming it then. The UI waits for that before it refetches, or the
   refetch brings the deleted draft back as the project's newest version. */

const apiJob = (over: Record<string, unknown> = {}) => ({
  id: 'job9', status: 'cancelled', phase: 3, phase_pct: 40, current_activity: '', activity_detail: '',
  elapsed_seconds: 60, eta_seconds: null, phases: [], commit_sha: 'abc1234', branch: 'main',
  version_id: 'ver9', version_tag: 'v2', mode: 'auto',
  started_at: '2026-10-01T09:00:00Z', completed_at: '2026-10-01T09:01:00Z', error_message: null,
  ...over,
})

/** The cancel answers `cancel`; each later read of the job answers the next of `reads`. */
function serve(cancel: object, reads: object[] = []) {
  const calls = { cancel: 0, get: 0 }
  server.use(
    http.post(`${API_BASE_URL}/projects/p1/jobs/job9/cancel`, () => {
      calls.cancel++
      return HttpResponse.json({ job: cancel })
    }),
    http.get(`${API_BASE_URL}/projects/p1/jobs/job9`, () => {
      const job = reads[Math.min(calls.get, reads.length - 1)]
      calls.get++
      return HttpResponse.json({ job })
    }),
  )
  return calls
}

describe('cancelJobAndWait', () => {
  it("waits until the server has deleted the run's draft version", async () => {
    const calls = serve(apiJob(), [apiJob(), apiJob(), apiJob({ version_id: null })])
    const job = await cancelJobAndWait('p1', 'job9', 1)
    expect(job.versionId).toBeNull()
    expect(calls).toEqual({ cancel: 1, get: 3 })
  })

  it('does not wait when the cancel already deleted the draft', async () => {
    const calls = serve(apiJob({ version_id: null }))
    expect((await cancelJobAndWait('p1', 'job9', 1)).status).toBe('cancelled')
    expect(calls.get).toBe(0)
  })

  it('does not wait for a job that adds documents: its version stays', async () => {
    const calls = serve(apiJob({ mode: 'export', version_id: 'ver1' }))
    expect((await cancelJobAndWait('p1', 'job9', 1)).versionId).toBe('ver1')
    expect(calls.get).toBe(0)
  })

  it('gives up waiting when the job cannot be read', async () => {
    serve(apiJob())
    server.use(http.get(`${API_BASE_URL}/projects/p1/jobs/job9`, () => new HttpResponse(null, { status: 500 })))
    expect((await cancelJobAndWait('p1', 'job9', 1)).versionId).toBe('ver9')
  })
})

describe('useCancelJob', () => {
  it("refetches the project's versions once the draft is gone", async () => {
    serve(apiJob({ version_id: null }))
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    client.setQueryData(projectKeys.versions('p1'), [{ id: 'ver9', status: 'draft' }])
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    const { result } = renderHook(() => useCancelJob('p1'), { wrapper })
    act(() => result.current.mutate('job9'))
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(client.getQueryState(projectKeys.versions('p1'))?.isInvalidated).toBe(true)
  })
})
