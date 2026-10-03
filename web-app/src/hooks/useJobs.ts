import { useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { jobsApi, functionsApi, versionsApi, type StartJobInput } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'
import { ApiError, isNotFound } from '../lib/http'
import { addsDocuments } from '../lib/runScope'
import type { AnalysisJob } from '../types'

/**
 * Subscribe to a job's SSE stream while it is active and refresh the cached job
 * on each event. The events endpoint is unauthenticated, so no token is needed.
 */
export function useJobEvents(projectId: string, jobId: string | undefined, status?: string) {
  const qc = useQueryClient()
  useEffect(() => {
    if (!projectId || !jobId) return
    if (status && !['queued', 'running', 'paused'].includes(status)) return
    const es = new EventSource(jobsApi.eventsUrl(projectId, jobId))
    const refresh = () => qc.invalidateQueries({ queryKey: projectKeys.job(projectId) })
    const close = () => { refresh(); es.close() }
    es.addEventListener('phase_update', refresh)
    es.addEventListener('activity_update', refresh)
    es.addEventListener('job_complete', close)
    es.addEventListener('job_failed', close)
    es.onerror = () => es.close()
    return () => es.close()
  }, [projectId, jobId, status, qc])
}

/** Current/latest job for a project. Polls while a job is active (SSE on the
 *  detail page provides finer-grained progress; this keeps cache fresh). */
export function useCurrentJob(projectId: string) {
  return useQuery({
    queryKey: projectKeys.job(projectId),
    queryFn: () => jobsApi.current(projectId),
    enabled: !!projectId,
    refetchInterval: (query) => {
      const job = query.state.data
      return job && ['queued', 'running', 'paused'].includes(job.status) ? 5000 : false
    },
  })
}

export function useJobFunctions(projectId: string, jobId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.jobFunctions(projectId, jobId ?? ''),
    queryFn: () => jobsApi.functions(projectId, jobId as string),
    enabled: !!projectId && !!jobId,
  })
}

/** After a job starts, stops or resumes: refetch the whole project — `detail` without `exact` is
 *  the prefix of every key of the project (job, versions, commits, documents, components). */
function useJobInvalidate(projectId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: projectKeys.job(projectId) })
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
  }
}

const RELEASE_POLL_MS = 1000
const RELEASE_POLLS = 20

/** The cancel was refused because the job had already ended (409 `JOB_FINISHED`): the job, when it
 *  ended `complete` (the run finished first) or `cancelled` (someone else's Stop got there first —
 *  two admins, or Stop pressed in two places); else nothing, and the refusal stands. */
async function endedBeforeCancel(projectId: string, jobId: string, e: unknown): Promise<AnalysisJob | null> {
  if (!(e instanceof ApiError) || e.status !== 409 || e.code !== 'JOB_FINISHED') return null
  try {
    const job = await jobsApi.get(projectId, jobId)
    return job.status === 'complete' || job.status === 'cancelled' ? job : null
  } catch {
    return null
  }
}

/**
 * Cancel a job and, for a version's own run, wait until the server has deleted its draft version.
 *
 * The server deletes the draft once the run's process has exited — a moment AFTER the cancel
 * answers, seconds for a big draft. A refetch before that brought the deleted draft back as the
 * project's newest version, and nothing refetched it again: the Overview showed an empty draft
 * instead of the last finished version. The job stops naming the version BEFORE the version is
 * gone, so it is the version that is asked: wait until its read answers 404 (at most ~20 s), then
 * let the caller refetch. A job that adds documents keeps its version.
 *
 * A run that finished before the cancel landed keeps its version: the job read says `complete`
 * (or the cancel answered 409 `JOB_FINISHED` for a complete job), and that job is returned —
 * `status: 'complete'` tells the caller the run was not cancelled. A 409 for a job someone else
 * cancelled first is a cancel like this one: the wait for its version goes on.
 */
export async function cancelJobAndWait(
  projectId: string, jobId: string, pollMs = RELEASE_POLL_MS,
): Promise<AnalysisJob> {
  let cancelled: AnalysisJob
  try {
    cancelled = await jobsApi.cancel(projectId, jobId)
  } catch (e) {
    const ended = await endedBeforeCancel(projectId, jobId, e)
    if (!ended) throw e
    if (ended.status === 'complete') return ended
    cancelled = ended
  }
  const versionId = cancelled.versionId
  if (!versionId || addsDocuments(cancelled.mode)) return cancelled
  for (let i = 0; i < RELEASE_POLLS; i++) {
    let now: AnalysisJob
    try {
      now = await jobsApi.get(projectId, jobId)
    } catch {
      return cancelled                 // cannot tell: the refetch shows whatever is there
    }
    if (now.status === 'complete') return now          // finished first: its version stays
    try {
      await versionsApi.get(projectId, versionId)
    } catch (e) {
      return isNotFound(e) ? now : cancelled           // 404: the draft is gone
    }
    await new Promise((resolve) => setTimeout(resolve, pollMs))
  }
  return cancelled
}

export function useStartJob(projectId: string) {
  const invalidate = useJobInvalidate(projectId)
  return useMutation({
    mutationFn: (body: StartJobInput) => jobsApi.start(projectId, body),
    onSuccess: () => { invalidate(); toast.success('Analysis started') },
    onError: (e: Error) => toast.error('Could not start analysis', e.message),
  })
}

/** Stop a job. Ask first (components/run/StopRunDialog): a generation's version goes with it. */
export function useCancelJob(projectId: string) {
  const invalidate = useJobInvalidate(projectId)
  return useMutation({
    mutationFn: (jobId: string) => cancelJobAndWait(projectId, jobId),
    onSuccess: (job) => {
      invalidate()
      if (job.status === 'complete') toast.info('The run had already finished', 'Its version was kept.')
      else toast.success('Job cancelled')
    },
    onError: (e: Error) => toast.error('Cancel failed', e.message),
  })
}

export function useResumeJob(projectId: string) {
  const invalidate = useJobInvalidate(projectId)
  return useMutation({
    mutationFn: (jobId: string) => jobsApi.resume(projectId, jobId),
    onSuccess: () => { invalidate(); toast.success('Job resumed') },
    onError: (e: Error) => toast.error('Resume failed', e.message),
  })
}

export function useSetVisibility(projectId: string, jobId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ fnId, isVisible }: { fnId: string; isVisible: boolean }) =>
      functionsApi.setVisibility(projectId, fnId, isVisible),
    onSuccess: () => {
      if (jobId) qc.invalidateQueries({ queryKey: projectKeys.jobFunctions(projectId, jobId) })
    },
    onError: (e: Error) => toast.error('Could not update visibility', e.message),
  })
}

export function useBulkVisibility(projectId: string, jobId: string | undefined) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ functionIds, isVisible }: { functionIds: string[]; isVisible: boolean }) =>
      functionsApi.bulkSetVisibility(projectId, functionIds, isVisible),
    onSuccess: () => {
      if (jobId) qc.invalidateQueries({ queryKey: projectKeys.jobFunctions(projectId, jobId) })
      toast.success('Visibility updated')
    },
    onError: (e: Error) => toast.error('Could not update visibility', e.message),
  })
}
