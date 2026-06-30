import { useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { jobsApi, functionsApi, type StartJobInput } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'

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

function useJobInvalidate(projectId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: projectKeys.job(projectId) })
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
  }
}

export function useStartJob(projectId: string) {
  const invalidate = useJobInvalidate(projectId)
  return useMutation({
    mutationFn: (body: StartJobInput) => jobsApi.start(projectId, body),
    onSuccess: () => { invalidate(); toast.success('Analysis started') },
    onError: (e: Error) => toast.error('Could not start analysis', e.message),
  })
}

export function useCancelJob(projectId: string) {
  const invalidate = useJobInvalidate(projectId)
  return useMutation({
    mutationFn: (jobId: string) => jobsApi.cancel(projectId, jobId),
    onSuccess: () => { invalidate(); toast.success('Job cancelled') },
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

export function useReexport(projectId: string) {
  return useMutation({
    mutationFn: (jobId: string) => jobsApi.reexport(projectId, jobId),
    onSuccess: () => toast.success('Re-export queued'),
    onError: (e: Error) => toast.error('Re-export failed', e.message),
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
