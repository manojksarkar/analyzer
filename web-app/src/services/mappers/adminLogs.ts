import { z } from 'zod'
import type { LogLevel, LogRecord, LogSource, LogTail } from '../../types'

/* Live logs (docs/spec/LIVE_LOGS_SPEC.md, REQ-LL-02): every record has the first seven fields; the
   rest only when known. Unknown extra fields pass (the record may grow). */
const LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'] as const

export const ApiLogRecordSchema = z.object({
  seq: z.number(),
  ts: z.string(),
  level: z.string(),
  source: z.string(),
  logger: z.string().nullable().optional(),
  message: z.string().nullable().optional(),
  pid: z.number().nullable().optional(),
  project: z.string().nullable().optional(),
  version: z.string().nullable().optional(),
  job: z.string().nullable().optional(),
  run: z.string().nullable().optional(),
  step: z.string().nullable().optional(),
  components: z.array(z.string()).nullable().optional(),
}).passthrough()
export type ApiLogRecord = z.infer<typeof ApiLogRecordSchema>

export const ApiLogTailSchema = z.object({
  records: z.array(ApiLogRecordSchema),
  cursor: z.number(),
  lines: z.number(),
  level: z.string(),
})
export type ApiLogTail = z.infer<typeof ApiLogTailSchema>

export const ApiLogTicketSchema = z.object({ ticket: z.string(), expiresIn: z.number() })

function level(v: string): LogLevel {
  const up = v.toUpperCase()
  return (LEVELS as readonly string[]).includes(up) ? (up as LogLevel) : 'INFO'
}

export const mapLogRecord = (r: ApiLogRecord): LogRecord => ({
  seq: r.seq,
  ts: r.ts,
  level: level(r.level),
  source: (r.source === 'engine' ? 'engine' : 'server') as LogSource,
  logger: r.logger ?? '',
  message: r.message ?? '',
  pid: r.pid ?? null,
  project: r.project ?? null,
  version: r.version ?? null,
  job: r.job ?? null,
  run: r.run ?? null,
  step: r.step ?? null,
  components: r.components ?? [],
})

export const mapLogTail = (t: ApiLogTail): LogTail => ({
  records: t.records.map(mapLogRecord),
  cursor: t.cursor,
  lines: t.lines,
  level: level(t.level),
})
