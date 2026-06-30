import { http } from '../../lib/http'
import type { AnalysisJob, JobFunctions, JobStatus } from '../../types'
import { mapJob, mapJobFunctions, type ApiJob, type ApiFunction } from '../mappers'

export interface StartJobInput {
  commit_sha: string
  version_tag?: string
  reference_version_id?: string
  pause_after_phase1?: boolean
  layer_filter?: string
}

export const jobsApi = {
  start: (projectId: string, body: StartJobInput): Promise<{ job_id: string; status: JobStatus }> =>
    http.post(`/projects/${projectId}/jobs`, body),
  current: async (projectId: string): Promise<AnalysisJob | null> => {
    const r = await http.get<{ job: ApiJob | null }>(`/projects/${projectId}/jobs/current`)
    return r.job ? mapJob(r.job) : null
  },
  get: async (projectId: string, jobId: string): Promise<AnalysisJob> => {
    const r = await http.get<{ job: ApiJob }>(`/projects/${projectId}/jobs/${jobId}`)
    return mapJob(r.job)
  },
  cancel: async (projectId: string, jobId: string): Promise<AnalysisJob> => {
    const r = await http.post<{ job: ApiJob }>(`/projects/${projectId}/jobs/${jobId}/cancel`)
    return mapJob(r.job)
  },
  resume: async (projectId: string, jobId: string): Promise<AnalysisJob> => {
    const r = await http.post<{ job: ApiJob }>(`/projects/${projectId}/jobs/${jobId}/resume`)
    return mapJob(r.job)
  },
  functions: async (projectId: string, jobId: string): Promise<JobFunctions> => {
    const r = await http.get<{
      functions: ApiFunction[]
      summary: { total: number; hidden: number; new_since_last: number }
    }>(`/projects/${projectId}/jobs/${jobId}/functions`)
    return mapJobFunctions(r)
  },
  reexport: (projectId: string, jobId: string): Promise<unknown> =>
    http.post(`/projects/${projectId}/jobs/${jobId}/reexport`),
  /** SSE endpoint URL. The events route is unauthenticated, so no token needed. */
  eventsUrl: (projectId: string, jobId: string): string =>
    http.rawUrl(`/projects/${projectId}/jobs/${jobId}/events`),
}

export const functionsApi = {
  setVisibility: (projectId: string, fnId: string, isVisible: boolean): Promise<unknown> =>
    http.patch(`/projects/${projectId}/functions/${fnId}`, { is_visible: isVisible }),
  bulkSetVisibility: (
    projectId: string,
    functionIds: string[],
    isVisible: boolean,
  ): Promise<{ updated_count: number }> =>
    http.patch(`/projects/${projectId}/functions`, {
      function_ids: functionIds,
      is_visible: isVisible,
    }),
}
