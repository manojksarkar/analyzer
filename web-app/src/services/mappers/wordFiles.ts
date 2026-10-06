import { z } from 'zod'
import type {
  ExportReadiness, OutOfDateFile, OutOfDateReason, SubmitWordFile, UserRef, VersionWriter, WordFileUpdateStart,
  WriterKind,
} from '../../types'

/* Word file updates (docs/design/WORD_FILE_UPDATES.md §4). R9 answers camelCase, as every review
   route; the reexport route, A5 and the errors answer snake_case. Every field here is optional on
   the wire: an API from before this contract sends none of them, and the page then says only what
   it can. */

/* ── R9 (camelCase) ── */

const ApiUserRefCamelSchema = z.object({ userId: z.string(), name: z.string(), initials: z.string() })

export const ApiOutOfDateSchema = z.object({
  documentId: z.string(),
  component: z.string(),
  name: z.string(),
  docType: z.string(),
  why: z.array(z.string()),
  corrections: z.number().optional(),
  pictures: z.number().optional(),
  layer: z.string().nullable().optional(),
  updating: z.boolean().optional(),
})
export type ApiOutOfDate = z.infer<typeof ApiOutOfDateSchema>

export const ApiWriterSchema = z.object({
  kind: z.string(),
  jobId: z.string().nullable().optional(),
  command: z.string().nullable().optional(),
  since: z.string().nullable().optional(),
  components: z.array(z.string()).nullable().optional(),
  componentsDone: z.number().nullable().optional(),
  componentsTotal: z.number().nullable().optional(),
  startedBy: ApiUserRefCamelSchema.nullable().optional(),
})
export type ApiWriter = z.infer<typeof ApiWriterSchema>

/** R9 `reexport`'s new fields (the newest update): scope, reason, components, progress, starter. */
export const ApiReexportExtrasSchema = z.object({
  scope: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
  components: z.array(z.string()).nullable().optional(),
  componentsDone: z.number().nullable().optional(),
  componentsFailed: z.array(z.string()).nullable().optional(),
  startedBy: ApiUserRefCamelSchema.nullable().optional(),
})
export type ApiReexportExtras = z.infer<typeof ApiReexportExtrasSchema>

/** R9's fields for Word file updates, beside the ones it always had (mappers/review.ts holds the
 *  whole R9 schema, these included). */
export const ApiWordFileReadinessSchema = z.object({
  outOfDate: z.array(ApiOutOfDateSchema).optional(),
  approvedKept: z.array(ApiOutOfDateSchema).optional(),
  writer: ApiWriterSchema.nullable().optional(),
  reexport: ApiReexportExtrasSchema.nullable().optional(),
})
export type ApiWordFileReadiness = z.infer<typeof ApiWordFileReadinessSchema>

const REASONS: OutOfDateReason[] = ['corrections', 'layerAdded', 'pictures']
const WRITER_KINDS: WriterKind[] = ['generation', 'update', 'rebuild', 'export', 'resume', 'other']

function mapReasons(why: string[]): OutOfDateReason[] {
  return why.filter((w): w is OutOfDateReason => (REASONS as string[]).includes(w))
}

export function mapOutOfDate(e: ApiOutOfDate): OutOfDateFile {
  return {
    documentId: e.documentId,
    component: e.component,
    name: e.name,
    docType: e.docType,
    why: mapReasons(e.why ?? []),
    corrections: e.corrections ?? 0,
    pictures: e.pictures ?? 0,
    layer: e.layer ?? null,
    updating: !!e.updating,
  }
}

function writerKind(k: string): WriterKind {
  return (WRITER_KINDS as string[]).includes(k) ? (k as WriterKind) : 'other'
}

export function mapWriter(w: ApiWriter | null | undefined): VersionWriter | null {
  if (!w) return null
  return {
    kind: writerKind(w.kind),
    jobId: w.jobId ?? null,
    command: w.command ?? null,
    since: w.since ?? null,
    components: w.components ?? null,
    componentsDone: w.componentsDone ?? null,
    componentsTotal: w.componentsTotal ?? null,
    startedBy: w.startedBy ?? null,
  }
}

/** R9's Word-file fields, to spread into the readiness (absent fields stay absent). */
export function mapWordFileReadiness(r: Omit<ApiWordFileReadiness, 'reexport'>): Pick<ExportReadiness, 'outOfDate' | 'approvedKept' | 'writer'> {
  return {
    ...(r.outOfDate ? { outOfDate: r.outOfDate.map(mapOutOfDate) } : {}),
    ...(r.approvedKept ? { approvedKept: r.approvedKept.map(mapOutOfDate) } : {}),
    ...(r.writer !== undefined ? { writer: mapWriter(r.writer) } : {}),
  }
}

/** The newest update's new fields (R9 `reexport`): scope, reason, components, progress, starter. */
export function mapReexportExtras(x: ApiReexportExtras): Partial<NonNullable<ExportReadiness['reexport']>> {
  return {
    ...(x.scope !== undefined ? { scope: x.scope } : {}),
    ...(x.reason !== undefined ? { reason: x.reason } : {}),
    ...(x.components ? { components: x.components } : {}),
    ...(typeof x.componentsDone === 'number' ? { componentsDone: x.componentsDone } : {}),
    ...(x.componentsFailed ? { componentsFailed: x.componentsFailed } : {}),
    ...(x.startedBy !== undefined ? { startedBy: x.startedBy } : {}),
  }
}

/* ── The platform routes (snake_case) ── */

const ApiUserRefSnakeSchema = z.object({ user_id: z.string(), name: z.string(), initials: z.string() })

/** `writer` / `blocked_by` as the platform routes send it (VERSION_BUSY, A5). */
export const ApiWriterSnakeSchema = z.object({
  kind: z.string(),
  job_id: z.string().nullable().optional(),
  command: z.string().nullable().optional(),
  since: z.string().nullable().optional(),
  components: z.array(z.string()).nullable().optional(),
  components_done: z.number().nullable().optional(),
  components_total: z.number().nullable().optional(),
  started_by: ApiUserRefSnakeSchema.nullable().optional(),
  message: z.string().nullable().optional(),
})
export type ApiWriterSnake = z.infer<typeof ApiWriterSnakeSchema>

function snakeUser(u: z.infer<typeof ApiUserRefSnakeSchema> | null | undefined): UserRef | null {
  return u ? { userId: u.user_id, name: u.name, initials: u.initials } : null
}

export function mapWriterSnake(w: ApiWriterSnake | null | undefined): VersionWriter | null {
  if (!w || typeof w !== 'object' || typeof w.kind !== 'string') return null
  return {
    kind: writerKind(w.kind),
    jobId: w.job_id ?? null,
    command: w.command ?? null,
    since: w.since ?? null,
    components: w.components ?? null,
    componentsDone: w.components_done ?? null,
    componentsTotal: w.components_total ?? null,
    startedBy: snakeUser(w.started_by),
    message: w.message ?? null,
  }
}

/** `POST V/reexport` → 202 started, 200 joined, 200 nothing out of date. */
export const ApiWordFileUpdateStartSchema = z.object({
  job_id: z.string().nullable(),
  status: z.string(),
  version_id: z.string().nullable().optional(),
  scope: z.string().nullable().optional(),
  components: z.array(z.string()).nullable().optional(),
  joined: z.boolean().optional(),
})
export type ApiWordFileUpdateStart = z.infer<typeof ApiWordFileUpdateStartSchema>

export function mapWordFileUpdateStart(r: ApiWordFileUpdateStart): WordFileUpdateStart {
  return {
    jobId: r.job_id ?? null,
    status: r.status,
    versionId: r.version_id ?? null,
    scope: r.scope ?? null,
    components: r.components ?? [],
    joined: !!r.joined,
  }
}

/** A5's `word_file`. */
export const ApiSubmitWordFileSchema = z.object({
  state: z.string(),
  job_id: z.string().nullable().optional(),
  blocked_by: ApiWriterSnakeSchema.nullable().optional(),
})
export type ApiSubmitWordFile = z.infer<typeof ApiSubmitWordFileSchema>

export function mapSubmitWordFile(w: ApiSubmitWordFile | null | undefined): SubmitWordFile | null {
  if (!w) return null
  const state = w.state === 'updating' || w.state === 'out_of_date' ? w.state : 'up_to_date'
  return { state, jobId: w.job_id ?? null, blockedBy: mapWriterSnake(w.blocked_by) }
}

/* ── Refusals (409 / 403 extra fields, snake_case) ── */

/** What an update refusal, a refused save or a refused approval carries beside its code. */
export interface WordFileRefusal {
  /** REEXPORT_RUNNING, WORD_FILE_UPDATING: the running one. */
  jobId: string | null
  /** REEXPORT_RUNNING: what runs — `update` | `rebuild` | `export` | `resume`. */
  kind: string | null
  /** REEXPORT_RUNNING: `out_of_date` | `all` | `export`. */
  scope: string | null
  /** REEXPORT_RUNNING, WORD_FILE_UPDATING: what it writes; NOT_YOUR_DOCUMENTS: the ones refused. */
  components: string[]
  /** VERSION_BUSY. */
  writer: VersionWriter | null
  /** STALE_EXPORT: why its Word file is out of date. */
  why: OutOfDateReason[]
  corrections: number
  pictures: number
  layer: string | null
}

const strOrNull = (v: unknown): string | null => (typeof v === 'string' ? v : null)
const num = (v: unknown): number => (typeof v === 'number' ? v : 0)
const strList = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [])

/** The extra fields of an error (ApiError.extra), read defensively. */
export function mapWordFileRefusal(extra: Record<string, unknown> | undefined): WordFileRefusal {
  const x = extra ?? {}
  return {
    jobId: strOrNull(x.job_id),
    kind: strOrNull(x.kind),
    scope: strOrNull(x.scope),
    components: strList(x.components),
    writer: mapWriterSnake(x.writer as ApiWriterSnake | undefined),
    why: mapReasons(strList(x.why)),
    corrections: num(x.corrections),
    pictures: num(x.pictures),
    layer: strOrNull(x.layer),
  }
}
