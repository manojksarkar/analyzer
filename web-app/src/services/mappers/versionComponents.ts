import { z } from 'zod'
import type {
  ComponentState, ProjectRun, ReviewStatus, RunFacts, RunSetting, RunSettings, VersionComponents, VersionRun,
} from '../../types'

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

/* GET /projects/{pid}/versions/{vid}/run-settings: each run of the version, this server's settings
   when it started (`output/_run_settings.json`, written by run.py; engine/core/config.py
   `run_settings_snapshot`). Lenient: a field added to the record later is passed over, one
   missing reads as unknown. */
const flexNum = z.union([z.number(), z.string()])
const ApiRunSettingSchema = z.object({
  at: z.string(),
  host: z.string().nullish(),
  code: z.string().nullish(),
  phases: z.array(z.number().nullable()).nullish(),
  docType: z.string().nullish(),
  components: z.array(z.string()).nullish(),
  llmServer: z.object({
    provider: z.string().nullish(), defaultModel: z.string().nullish(), baseUrl: z.string().nullish(),
    apiKey: z.string().nullish(), customHeaders: z.array(z.string()).nullish(),
  }).passthrough().nullish(),
  headersFromEnvironment: z.array(z.string()).nullish(),
  speedups: z.object({
    llms: z.array(z.object({ name: z.string(), maxConcurrent: flexNum.nullish() }).passthrough()).nullish(),
    pacing: z.string().nullish(),
    parseWorkers: flexNum.nullish(),
  }).passthrough().nullish(),
  llvm: z.object({ libPath: z.string().nullish(), includePath: z.string().nullish() }).passthrough().nullish(),
}).passthrough()
export const ApiRunSettingsSchema = z.object({
  version_id: z.string(),
  running: z.boolean(),
  runs: z.array(ApiRunSettingSchema),
})
export type ApiRunSettings = z.infer<typeof ApiRunSettingsSchema>

const PHASES = ['Parse', 'Derive', 'Views', 'Documents']
const DOC_TYPES: Record<string, string> = { swe3: 'SWE.3', swe4: 'SWE.4' }

/** "Parse", "Derive · Views · Documents", "Documents (SWE.3)" -- from the run's phases. */
function runWhat(phases: (number | null)[] | null | undefined, docType: string | null | undefined): string {
  const [from, to] = phases ?? []
  const first = Math.min(Math.max(from ?? 1, 1), 4)
  const last = Math.min(Math.max(to ?? 4, first), 4)
  const steps = PHASES.slice(first - 1, last).join(' · ')
  const doc = docType ? DOC_TYPES[docType] : undefined
  return doc ? `${steps} (${doc})` : steps
}

function listShort(names: string[], keep = 3): string {
  if (names.length <= keep) return names.join(', ')
  return `${names.slice(0, keep).join(', ')} and ${names.length - keep} more`
}

const mapRunSetting = (r: z.infer<typeof ApiRunSettingSchema>): RunSetting => {
  const server = r.llmServer ?? {}
  const headers = [...(server.customHeaders ?? []), ...(r.headersFromEnvironment ?? [])]
  const workers = String(r.speedups?.parseWorkers ?? '1')
  const n = workers.split('->').pop()?.trim() ?? workers
  return {
    at: r.at,
    what: runWhat(r.phases, r.docType),
    components: r.components?.length ? listShort(r.components) : 'all components',
    llm: `${server.provider ?? '?'} / ${server.defaultModel ?? '?'}`,
    endpoint: server.baseUrl ?? null,
    lanes: (r.speedups?.llms ?? []).map((l) => ({ name: l.name, atOnce: String(l.maxConcurrent ?? 1) })),
    credentials: `API key ${server.apiKey ?? 'none'}${headers.length ? ` · headers ${headers.join(', ')}` : ''}`,
    pacing: r.speedups?.pacing ?? null,
    parsing: `${workers.includes('auto') ? 'auto → ' : ''}${n} file${n === '1' ? '' : 's'} at once`,
    llvm: r.llvm?.libPath || null,
    host: r.host ?? null,
    code: r.code ?? null,
  }
}

/** Newest first: the drawer reads down from the run you are most likely asking about. */
export const mapRunSettings = (r: ApiRunSettings): RunSettings => ({
  running: r.running,
  runs: r.runs.map(mapRunSetting).reverse(),
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
