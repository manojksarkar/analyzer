import { z } from 'zod'
import type { ComponentState, ReviewStatus, VersionComponents } from '../../types'

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
})
export type ApiVersionComponents = z.infer<typeof ApiVersionComponentsSchema>

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
      error: c.error ?? null,
      documents: c.documents.map((d) => ({ id: d.id, process: d.process, status: d.status as ReviewStatus })),
    })),
    counts,
    run: r.run
      ? {
          command: r.run.command ?? '',
          alive: r.run.alive ?? null,
          stopped: !!r.run.stopped,
          outcome: r.run.outcome ?? '',
          host: r.run.host ?? null,
          startedAt: r.run.started_at ?? null,
          finishedAt: r.run.finished_at ?? null,
          stage: r.run.stage ?? null,
          done: r.run.done ?? null,
          total: r.run.total ?? null,
          stageStartedAt: r.run.stage_started_at ?? null,
          progressAt: r.run.progress_at ?? null,
        }
      : null,
    job: r.job ? { id: r.job.id, mode: r.job.mode ?? 'auto', status: r.job.status } : null,
  }
}
