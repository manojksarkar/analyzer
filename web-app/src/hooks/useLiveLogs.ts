import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { adminLogsApi } from '../services/api'
import { ApiLogRecordSchema, mapLogRecord } from '../services/mappers'
import { ApiError } from '../lib/http'
import type { LogFilters, LogRecord } from '../types'

/* Live logs (docs/spec/LIVE_LOGS_SPEC.md): the tail as a read, then a stream that continues after
   its cursor. A stream signs in by a single-use ticket, so every stream opened — a reconnect
   too — takes a new one, and asks for what follows the last `seq` seen. A `gap` (the API restarted,
   or the page was away long) reads the tail again. Lines arriving in a burst (DEBUG during a
   parse: hundreds a second) are drawn at most every 250 ms, and at most `lines` are kept. */

export const adminKeys = {
  all: ['admin'] as const,
  logs: (f: LogFilters) => ['admin', 'logs', f] as const,
  recent: (project: string, version: string) => ['admin', 'logs', 'recent', project, version] as const,
}

/** A run's newest three lines (superusers: the Overview, under the running card), every 5 s. */
export function useRecentLogLines(project: string, version: string | null | undefined, enabled: boolean) {
  return useQuery({
    queryKey: adminKeys.recent(project, version ?? ''),
    queryFn: () => adminLogsApi.tail({ level: 'INFO', project, version: version as string }, 3),
    enabled: enabled && !!project && !!version,
    refetchInterval: 5_000,
    retry: false,
  })
}

export type LiveStatus = 'connecting' | 'live' | 'reconnecting' | 'stopped'

/** Seconds before each reconnect: 1, 2, 5, 10, then every 30. */
export const BACKOFF = [1, 2, 5, 10, 30]
const FLUSH_MS = 250

/** A sign-in the user cannot fix by waiting: signed out (after the client's own refresh) or not a
 *  superuser. The stream stops instead of retrying. */
const isAuthError = (e: unknown) => e instanceof ApiError && (e.status === 401 || e.status === 403)

export function useLiveLogs(filters: LogFilters) {
  const qc = useQueryClient()
  const key = adminKeys.logs(filters)
  const tail = useQuery({
    queryKey: key,
    queryFn: () => adminLogsApi.tail(filters),
    // The stream keeps it current: never read again on its own.
    staleTime: Infinity,
    gcTime: 0,
    refetchOnWindowFocus: false,
    retry: (n, e) => !isAuthError(e) && n < 2,
  })
  const tailAt = tail.dataUpdatedAt
  const cap = tail.data?.lines ?? 500

  // Lines streamed since the tail was read. Kept with the read they follow, so a new tail starts
  // them again without an effect that clears state.
  const [live, setLive] = useState<{ at: number; items: LogRecord[] }>({ at: 0, items: [] })
  const [status, setStatus] = useState<LiveStatus>('connecting')
  const [retryIn, setRetryIn] = useState<number | null>(null)
  const [attempt, setAttempt] = useState(0)
  const lastSeq = useRef({ at: 0, seq: 0 })

  const filtersKey = JSON.stringify(key)
  const cursor = tail.data?.cursor
  useEffect(() => {
    if (cursor === undefined) return
    if (lastSeq.current.at !== tailAt) lastSeq.current = { at: tailAt, seq: cursor }
    const f: LogFilters = JSON.parse(filtersKey)[2]
    let es: EventSource | null = null
    let cancelled = false
    let fails = 0
    let retryTimer: number | undefined
    let flushTimer: number | undefined
    const queue: LogRecord[] = []

    const flush = () => {
      flushTimer = undefined
      if (!queue.length) return
      const batch = queue.splice(0)
      setLive((prev) => {
        const items = (prev.at === tailAt ? prev.items : []).concat(batch)
        return { at: tailAt, items: items.length > cap ? items.slice(-cap) : items }
      })
    }
    const retry = () => {
      if (cancelled) return
      const s = BACKOFF[Math.min(fails, BACKOFF.length - 1)]
      fails += 1
      setStatus('reconnecting')
      setRetryIn(s)
      retryTimer = window.setTimeout(() => { void open() }, s * 1000)
    }
    const open = async () => {
      let ticket: string
      try {
        ticket = await adminLogsApi.ticket()
      } catch (e) {
        if (cancelled) return
        if (isAuthError(e)) { setStatus('stopped'); setRetryIn(null); return }
        retry()
        return
      }
      if (cancelled) return
      es = new EventSource(adminLogsApi.streamUrl(ticket, f, lastSeq.current.seq))
      es.onopen = () => { fails = 0; setStatus('live'); setRetryIn(null) }
      es.addEventListener('log', (ev) => {
        try {
          const r = mapLogRecord(ApiLogRecordSchema.parse(JSON.parse((ev as MessageEvent).data)))
          if (r.seq <= lastSeq.current.seq) return             // already shown
          lastSeq.current.seq = r.seq
          queue.push(r)
          if (flushTimer === undefined) flushTimer = window.setTimeout(flush, FLUSH_MS)
        } catch { /* a record the page cannot read is skipped, never shown half */ }
      })
      es.addEventListener('gap', () => {
        // Lines were lost between the last one seen and what the server still holds: start again
        // from a fresh tail (its new data runs this effect again).
        es?.close()
        es = null
        void qc.refetchQueries({ queryKey: JSON.parse(filtersKey), exact: true })
      })
      // The browser's own retry would reuse the spent ticket (401): close it and open a new one.
      es.onerror = () => { es?.close(); es = null; retry() }
    }
    void open()
    return () => {
      cancelled = true
      es?.close()
      window.clearTimeout(retryTimer)
      window.clearTimeout(flushTimer)
    }
  }, [cursor, tailAt, filtersKey, attempt, cap, qc])

  const streamed = live.at === tailAt ? live.items : null
  const rows = useMemo(() => {
    const all = (tail.data?.records ?? []).concat(streamed ?? [])
    return all.length > cap ? all.slice(-cap) : all
  }, [tail.data, streamed, cap])

  const tailError = tail.error
  return {
    rows,
    cap,
    loading: tail.isLoading,
    /** 403: not a superuser; anything else: the tail could not be read. */
    forbidden: tailError instanceof ApiError && tailError.status === 403,
    error: tailError,
    status: tail.data ? (tailError ? 'stopped' : status) : (tailError ? 'stopped' : 'connecting'),
    retryIn,
    /** After Stopped: sign-in fixed, try again from the last line seen. */
    reconnect: () => { setStatus('connecting'); setAttempt((a) => a + 1) },
  }
}
