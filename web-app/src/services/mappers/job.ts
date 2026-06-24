import type { AnalysisJob, JobPhase, JobFunctions } from '../../types'
import { shortSha } from '../../lib/format'

export interface ApiJobPhase { number: number; name: string; status: string; duration_seconds: number | null }
export interface ApiJob {
  id: string; status: string; phase: number; phase_pct: number
  current_activity: string; activity_detail: string
  elapsed_seconds: number; eta_seconds: number | null; phases: ApiJobPhase[]
  commit_sha: string; branch: string; version_id: string | null; version_tag?: string | null
  started_at: string | null; completed_at: string | null; error_message: string | null
}

export interface ApiFunction {
  id: string; name: string; file_path: string; layer: string; group: string
  is_visible: boolean; is_new: boolean; description: string
}

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
