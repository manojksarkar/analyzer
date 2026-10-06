import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { useLiveLogs } from '../useLiveLogs'
import type { LogFilters } from '../../types'

/* Live logs (docs/spec/LIVE_LOGS_SPEC.md): the tail, then a stream that continues after its cursor.
   Every stream takes a new single-use ticket and asks for what follows the last line seen; a gap
   reads the tail again; at most `lines` are kept. */

class FakeEventSource {
  static all: FakeEventSource[] = []
  url: string
  closed = false
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  private listeners: Record<string, ((e: MessageEvent) => void)[]> = {}
  constructor(url: string) {
    this.url = url
    FakeEventSource.all.push(this)
  }
  addEventListener(type: string, f: (e: MessageEvent) => void) {
    ;(this.listeners[type] ??= []).push(f)
  }
  close() { this.closed = true }
  emit(type: string, data: unknown) {
    for (const f of this.listeners[type] ?? []) f({ data: JSON.stringify(data) } as MessageEvent)
  }
  param(name: string) { return new URL(this.url).searchParams.get(name) }
}
const last = () => FakeEventSource.all[FakeEventSource.all.length - 1]

const rec = (seq: number, over: Record<string, unknown> = {}) => ({
  seq, ts: `2026-10-06T10:15:0${seq % 10}.420+05:30`, level: 'INFO', source: 'engine',
  logger: 'parser', message: `line ${seq}`, pid: 7832, ...over,
})

/** The tail answers each read with the next of `tails`; tickets are numbered t1, t2, … */
function serve(tails: { records: object[]; cursor: number; lines?: number }[], ticket: number | 'deny' = 200) {
  const calls = { tail: [] as URLSearchParams[], tickets: 0 }
  server.use(
    http.get(`${API_BASE_URL}/admin/logs`, ({ request }) => {
      const t = tails[Math.min(calls.tail.length, tails.length - 1)]
      calls.tail.push(new URL(request.url).searchParams)
      return HttpResponse.json({ records: t.records, cursor: t.cursor, lines: t.lines ?? 500, level: 'INFO' })
    }),
    http.post(`${API_BASE_URL}/admin/logs/ticket`, () => {
      calls.tickets++
      if (ticket === 'deny') {
        return HttpResponse.json({ detail: { code: 'FORBIDDEN', message: 'Superusers only.', status: 403 } }, { status: 403 })
      }
      return HttpResponse.json({ ticket: `t${calls.tickets}`, expiresIn: 60 })
    }),
  )
  return calls
}

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>
}
const INFO: LogFilters = { level: 'INFO' }

describe('useLiveLogs', () => {
  beforeEach(() => { FakeEventSource.all = []; vi.stubGlobal('EventSource', FakeEventSource) })
  afterEach(() => vi.unstubAllGlobals())

  it('shows the tail, then opens the stream after its cursor with a ticket and the filters', async () => {
    const calls = serve([{ records: [rec(1), rec(2)], cursor: 9 }])
    const { result } = renderHook(() => useLiveLogs({ level: 'WARNING', job: 'job1' }), { wrapper })
    await waitFor(() => expect(result.current.rows.map((r) => r.seq)).toEqual([1, 2]))
    expect(calls.tail[0].get('level')).toBe('WARNING')
    expect(calls.tail[0].get('job')).toBe('job1')
    await waitFor(() => expect(FakeEventSource.all).toHaveLength(1))
    expect(last().param('ticket')).toBe('t1')
    expect(last().param('after')).toBe('9')
    expect(last().param('level')).toBe('WARNING')
    expect(last().param('job')).toBe('job1')
    act(() => last().onopen?.())
    expect(result.current.status).toBe('live')
  })

  it('appends streamed lines, once each, and keeps at most `lines`', async () => {
    serve([{ records: [rec(1), rec(2), rec(3)], cursor: 3, lines: 3 }])
    const { result } = renderHook(() => useLiveLogs(INFO), { wrapper })
    await waitFor(() => expect(FakeEventSource.all).toHaveLength(1))
    act(() => {
      last().emit('log', rec(4))
      last().emit('log', rec(4))          // the same line again: shown once
      last().emit('log', rec(5, { level: 'WARNING', components: ['Layer1.Sample Core'] }))
    })
    await waitFor(() => expect(result.current.rows.map((r) => r.seq)).toEqual([3, 4, 5]))
    expect(result.current.rows[2]).toMatchObject({ level: 'WARNING', components: ['Layer1.Sample Core'], job: null })
  })

  it('a gap reads the tail again and continues after its new cursor', async () => {
    const calls = serve([{ records: [rec(1)], cursor: 1 }, { records: [rec(7), rec(8)], cursor: 8 }])
    const { result } = renderHook(() => useLiveLogs(INFO), { wrapper })
    await waitFor(() => expect(FakeEventSource.all).toHaveLength(1))
    const first = last()
    act(() => first.emit('gap', { cursor: 8 }))
    await waitFor(() => expect(result.current.rows.map((r) => r.seq)).toEqual([7, 8]))
    expect(first.closed).toBe(true)
    expect(calls.tail).toHaveLength(2)
    await waitFor(() => expect(FakeEventSource.all).toHaveLength(2))
    expect(last().param('after')).toBe('8')
    expect(last().param('ticket')).toBe('t2')
  })

  it('a dropped stream comes back with a new ticket, after the last line seen', async () => {
    const calls = serve([{ records: [rec(1)], cursor: 1 }])
    const { result } = renderHook(() => useLiveLogs(INFO), { wrapper })
    await waitFor(() => expect(FakeEventSource.all).toHaveLength(1))
    act(() => last().emit('log', rec(5)))
    await waitFor(() => expect(result.current.rows).toHaveLength(2))
    const first = last()
    act(() => first.onerror?.())
    expect(first.closed).toBe(true)
    await waitFor(() => expect(result.current.status).toBe('reconnecting'))
    expect(result.current.retryIn).toBe(1)
    await waitFor(() => expect(FakeEventSource.all).toHaveLength(2), { timeout: 3000 })
    expect(last().param('after')).toBe('5')
    expect(last().param('ticket')).toBe('t2')
    expect(calls.tail).toHaveLength(1)                    // the lines shown stay
  })

  it('stops, rather than retrying, when the ticket is refused', async () => {
    serve([{ records: [rec(1)], cursor: 1 }], 'deny')
    const { result } = renderHook(() => useLiveLogs(INFO), { wrapper })
    await waitFor(() => expect(result.current.status).toBe('stopped'))
    expect(FakeEventSource.all).toHaveLength(0)
  })

  it('a refused tail says superusers only', async () => {
    server.use(http.get(`${API_BASE_URL}/admin/logs`, () =>
      HttpResponse.json({ detail: { code: 'FORBIDDEN', message: 'Superusers only.', status: 403 } }, { status: 403 })))
    const { result } = renderHook(() => useLiveLogs(INFO), { wrapper })
    await waitFor(() => expect(result.current.forbidden).toBe(true))
    expect(result.current.status).toBe('stopped')
  })
})
