import { http } from '../../lib/http'
import type { AnalysisJob, JobFunctions, JobStatus } from '../../types'
import { mapJob, mapJobFunctions, type ApiJob, type ApiFunction } from '../mappers'

/** What a run analyses: `names` of ONE kind - layer names, or layer-qualified group or component
 *  ids (`Layer1.My Sample`, `Layer1.Lib`). Several may be named, from different layers. */
export interface JobScope {
  type: 'project' | 'layer' | 'group' | 'component'
  names: string[]
}

export interface StartJobInput {
  commit_sha: string
  version_tag?: string
  reference_version_id?: string
  pause_after_phase1?: boolean
  /** Narrows the run. The server's generation command reads `scope`, not `layer_filter`. */
  scope?: JobScope
  /** Skip the LLM steps (the engine's `--no-llm`): faster, for checking structure, not wording. */
  no_llm?: boolean
  /** `full`: a fresh run, nothing taken from an earlier version (`generate --full`). Not sent:
   *  `auto`, the newest earlier version (or `reference_version_id`) is the baseline. */
  mode?: 'auto' | 'full'
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
  /** Pause (NW-1): the run stops before its next step and keeps what it made; `resume` carries
   *  the same job on. */
  pause: async (projectId: string, jobId: string): Promise<AnalysisJob> => {
    const r = await http.post<{ job: ApiJob }>(`/projects/${projectId}/jobs/${jobId}/pause`)
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
  /** The version a run of `commit` would build on, when none is picked (read-only: no checkout).
   *  `null`: none — the run is a fresh one anyway. */
  baselinePreview: async (projectId: string, commit: string): Promise<string | null> => {
    const r = await http.get<{ chosenBaseVersionId?: string | null }>(
      `/projects/${projectId}/baseline-preview`, { commit })
    return r.chosenBaseVersionId ?? null
  },
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
