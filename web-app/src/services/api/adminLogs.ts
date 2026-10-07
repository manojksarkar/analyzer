import { http } from '../../lib/http'
import type { LogFilters, LogTail } from '../../types'
import { ApiLogTailSchema, ApiLogTicketSchema, mapLogTail } from '../mappers'

/* Live logs, superusers only (docs/spec/LIVE_LOGS_SPEC.md): the tail, then a stream that continues
   after its cursor. The stream signs in by a single-use ticket — an EventSource cannot send the
   bearer token — so every stream opened, a reconnect too, takes a new one. */

/** The server filters as query parameters: empty ones are left out. */
const params = (f: LogFilters) => ({
  level: f.level, source: f.source, project: f.project, version: f.version, job: f.job,
})

export const adminLogsApi = {
  /** `lines`: how many (the server's default, 500, when left out). */
  tail: async (filters: LogFilters, lines?: number): Promise<LogTail> =>
    mapLogTail(ApiLogTailSchema.parse(await http.get('/admin/logs', { ...params(filters), lines }))),
  /** Opens ONE stream within 60 s. */
  ticket: async (): Promise<string> =>
    ApiLogTicketSchema.parse(await http.post('/admin/logs/ticket')).ticket,
  /** `after`: the last `seq` seen — the stream sends only what follows it. */
  streamUrl: (ticket: string, filters: LogFilters, after: number) =>
    http.rawUrl('/admin/logs/stream', { ticket, after, ...params(filters) }),
}
