import { z } from 'zod'
import type { ComponentState, ProjectRun, ReviewStatus, RunFacts, VersionComponents, VersionRun } from '../../types'

/* Staged generation (GET /projects/{pid}/versions/{vid}/components): every component of the layers
   the version parsed — and those its config names in layers the model lacks yet (`in_model` and
   `layer_parsed` false) — the state of its documents, and the version's latest run. snake_case on
   the wire. */

const STATES: ComponentState[] = ['generated', 'generating', 'waiting', 'stopped', 'failed', 'stale', 'not_requested']

export const ApiVersionComponentSchema = z.object({
  component: z.string(),
  layer: z.string(),
  name: z.string(),
  state: z.string(),
  in_model: z.boolean(),
  /** Absent from an older API, which listed only the parsed layers' components. */
  layer_parsed: z.boolean().optional(),
  /** Its group in the version's configuration; absent from an older API. */
  group: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
  documents: z.array(z.object({ id: z.string(), process: z.string(), status: z.string() })),
})

export const ApiVersionRunSchema = z.object({
  command: z.string().nullable().optional(),
  alive: z.boolean().nullable().optional(),
  stopped: z.boolean().optional(),
  outcome: z.string().nullable().optional(),
  host: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  stage: z.string().nullable().optional(),
  done: z.number().nullable().optional(),
  total: z.number().nullable().optional(),
  stage_started_at: z.string().nullable().optional(),
  progress_at: z.string().nullable().optional(),
})

export const ApiVersionComponentsSchema = z.object({
  version_id: z.string(),
  components: z.array(ApiVersionComponentSchema),
  counts: z.record(z.string(), z.number()),
  run: ApiVersionRunSchema.nullable(),
  job: z.object({ id: z.string(), mode: z.string().nullable().optional(), status: z.string() })
    .nullable().optional(),
  resume_action: z.string().nullable().optional(),
})
export type ApiVersionComponents = z.infer<typeof ApiVersionComponentsSchema>

export const ApiRunFactsSchema = z.object({
  version_id: z.string(),
  model: z.object({ functions: z.number(), globals: z.number(), units: z.number(), components: z.number() }).nullable(),
  llm: z.object({
    failed_calls: z.number(), retries: z.number(),
    last_failure: z.object({ ts: z.string().nullable().optional(), message: z.string() }).nullable(),
  }),
  parse: z.object({ warnings: z.number() }),
})
export type ApiRunFacts = z.infer<typeof ApiRunFactsSchema>

export const mapRunFacts = (r: ApiRunFacts): RunFacts => ({
  model: r.model,
  llm: {
    retries: r.llm.retries, failedCalls: r.llm.failed_calls,
    lastFailure: r.llm.last_failure ? { ts: r.llm.last_failure.ts ?? null, message: r.llm.last_failure.message } : null,
  },
  parseWarnings: r.parse.warnings,
})

/** GET /projects/{pid}/runs: the runs at work now, or cut short, whichever front door started them. */
export const ApiProjectRunsSchema = z.object({
  runs: z.array(ApiVersionRunSchema.extend({ version_id: z.string(), version_tag: z.string().nullable().optional() })),
})
export type ApiProjectRuns = z.infer<typeof ApiProjectRunsSchema>

export function mapVersionRun(r: z.infer<typeof ApiVersionRunSchema>): VersionRun {
  return {
    command: r.command ?? '',
    alive: r.alive ?? null,
    stopped: !!r.stopped,
    outcome: r.outcome ?? '',
    host: r.host ?? null,
    startedAt: r.started_at ?? null,
    finishedAt: r.finished_at ?? null,
    stage: r.stage ?? null,
    done: r.done ?? null,
    total: r.total ?? null,
    stageStartedAt: r.stage_started_at ?? null,
    progressAt: r.progress_at ?? null,
  }
}

export function mapProjectRuns(r: ApiProjectRuns): ProjectRun[] {
  return r.runs.map((x) => ({ ...mapVersionRun(x), versionId: x.version_id, versionTag: x.version_tag ?? x.version_id }))
}

const asState = (s: string): ComponentState =>
  (STATES as string[]).includes(s) ? (s as ComponentState) : 'not_requested'

export function mapVersionComponents(r: ApiVersionComponents): VersionComponents {
  const counts: VersionComponents['counts'] = {}
  for (const [k, v] of Object.entries(r.counts ?? {})) counts[asState(k)] = v
  return {
    components: r.components.map((c) => ({
      id: c.component,
      layer: c.layer,
      name: c.name,
      state: asState(c.state),
      inModel: c.in_model,
      layerParsed: c.layer_parsed ?? true,
      group: c.group ?? null,
      error: c.error ?? null,
      documents: c.documents.map((d) => ({ id: d.id, process: d.process, status: d.status as ReviewStatus })),
    })),
    counts,
    run: r.run ? mapVersionRun(r.run) : null,
    job: r.job ? { id: r.job.id, mode: r.job.mode ?? 'auto', status: r.job.status } : null,
    resumeAction: r.resume_action ?? null,
  }
}
