import { z } from 'zod'
import type { AnalysisJob, JobPhase, JobFunctions } from '../../types'
import { shortSha } from '../../lib/format'

export const ApiJobPhaseSchema = z.object({
  number: z.number(), name: z.string(), status: z.string(), duration_seconds: z.number().nullable(),
})
export type ApiJobPhase = z.infer<typeof ApiJobPhaseSchema>

export const ApiJobSchema = z.object({
  id: z.string(), status: z.string(), phase: z.number(), phase_pct: z.number(),
  current_activity: z.string(), activity_detail: z.string(),
  elapsed_seconds: z.number(), eta_seconds: z.number().nullable(), phases: z.array(ApiJobPhaseSchema),
  commit_sha: z.string(), branch: z.string(), version_id: z.string().nullable(),
  version_tag: z.string().nullable().optional(),
  started_at: z.string().nullable(), completed_at: z.string().nullable(), error_message: z.string().nullable(),
})
export type ApiJob = z.infer<typeof ApiJobSchema>

export const ApiFunctionSchema = z.object({
  id: z.string(), name: z.string(), file_path: z.string(), layer: z.string(), group: z.string(),
  is_visible: z.boolean(), is_new: z.boolean(), description: z.string(),
})
export type ApiFunction = z.infer<typeof ApiFunctionSchema>

const mapJobPhase = (p: ApiJobPhase): JobPhase => ({
  number: p.number, name: p.name, status: p.status as JobPhase['status'],
  durationSeconds: p.duration_seconds,
})

export function mapJob(j: ApiJob): AnalysisJob {
  return {
    id: j.id,
    status: j.status as AnalysisJob['status'],
    phase: j.phase,
    phasePct: j.phase_pct,
    currentActivity: j.current_activity,
    activityDetail: j.activity_detail,
    elapsedSeconds: j.elapsed_seconds,
    etaSeconds: j.eta_seconds,
    phases: (j.phases ?? []).map(mapJobPhase),
    commitSha: j.commit_sha,
    shortSha: shortSha(j.commit_sha),
    branch: j.branch,
    versionId: j.version_id,
    versionTag: j.version_tag ?? null,
    startedAt: j.started_at,
    completedAt: j.completed_at,
    errorMessage: j.error_message,
  }
}

export function mapJobFunctions(
  payload: { functions: ApiFunction[]; summary: { total: number; hidden: number; new_since_last: number } }
): JobFunctions {
  return {
    functions: payload.functions.map((f) => ({
      id: f.id, name: f.name, filePath: f.file_path, layer: f.layer, group: f.group,
      isVisible: f.is_visible, isNew: f.is_new, description: f.description,
    })),
    summary: {
      total: payload.summary.total,
      hidden: payload.summary.hidden,
      newSinceLast: payload.summary.new_since_last,
    },
  }
}
