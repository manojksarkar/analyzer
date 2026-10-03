import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { useCommits, useCommitsLastSync } from '../useProjects'

/* The commits route answers 20 a page by default (at most 100) and has no search; the Run modal
   and the Subbar pick from what useCommits returns, so it must return every page. */

/** Commit `i`, a minute older than commit `i - 1` (so the newest-first order is by `i`). */
const apiCommit = (i: number, sha = `sha${String(i).padStart(4, '0')}`) => ({
  sha, message: `commit ${i}`, author: 'Dev',
  committed_at: new Date(Date.UTC(2026, 9, 1) - i * 60_000).toISOString(), branch: 'main',
  doc_status: 'never', version: null, is_current: false,
})

interface Serve {
  withTotal?: boolean
  /** Pages that answer 500. */
  failing?: number[]
  /** Runs after page 1 is answered: the repo sync it starts (commits pushed meanwhile). */
  afterFirst?: (all: ReturnType<typeof apiCommit>[]) => void
  commits?: ReturnType<typeof apiCommit>[]
}

function serve(count: number, { withTotal = true, failing = [], afterFirst, commits }: Serve = {}) {
  const all = commits ?? Array.from({ length: count }, (_, i) => apiCommit(i + 1))
  const asked: { page: number; perPage: number }[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/commits`, ({ request }) => {
      const url = new URL(request.url)
      const page = Number(url.searchParams.get('page') ?? 1)
      const perPage = Math.min(Number(url.searchParams.get('per_page') ?? 20), 100)
      asked.push({ page, perPage })
      if (failing.includes(page)) return new HttpResponse(null, { status: 500 })
      if (page === 1 && afterFirst) {
        const answer = HttpResponse.json({
          commits: all.slice(0, perPage),
          ...(withTotal ? { pagination: { page, per_page: perPage, total: all.length } } : {}),
          last_synced_at: '2026-10-01T10:00:00+00:00',
        })
        afterFirst(all)
        return answer
      }
      return HttpResponse.json({
        commits: all.slice((page - 1) * perPage, page * perPage),
        ...(withTotal ? { pagination: { page, per_page: perPage, total: all.length } } : {}),
        last_synced_at: '2026-10-01T10:00:00+00:00',
      })
    }),
  )
  return asked
}

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

describe('useCommits', () => {
  it('returns every stored commit, not the first page of 20', async () => {
    const asked = serve(250)
    const { result } = renderHook(() => useCommits('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(250)
    expect(result.current.data?.[249].sha).toBe('sha0250')
    // Page 1 first (it is the read that syncs the repo), then the rest.
    expect(asked[0]).toEqual({ page: 1, perPage: 100 })
    expect(asked.map((a) => a.page).sort()).toEqual([1, 2, 3])
  })

  it('reads one page when there are 100 or fewer', async () => {
    const asked = serve(5)
    const { result } = renderHook(() => useCommits('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(5)
    expect(asked).toHaveLength(1)
  })

  it('reads on until a short page when the API does not say the total', async () => {
    const asked = serve(130, { withTotal: false })
    const { result } = renderHook(() => useCommits('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(130)
    expect(asked.map((a) => a.page)).toEqual([1, 2])
  })

  it('reads on past the counted pages when a push lands during the read: the oldest are kept', async () => {
    // Page 1 counts 200; the sync it starts then adds 5 newer commits, which push the oldest 5
    // off page 2 onto a page 3 the total never counted.
    const asked = serve(200, {
      afterFirst: (all) => all.unshift(...Array.from({ length: 5 }, (_, i) => apiCommit(-1 - i, `new${i}`))),
    })
    const { result } = renderHook(() => useCommits('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(asked.map((a) => a.page)).toEqual([1, 2, 3])
    expect(result.current.data).toHaveLength(200)
    expect(result.current.data?.at(-1)?.sha).toBe('sha0200')
  })

  it('a page that fails is left out; the rest still come', async () => {
    serve(250, { failing: [2] })
    const { result } = renderHook(() => useCommits('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(150)
    expect(result.current.data?.[100].sha).toBe('sha0201')
  })

  it('newest first, and commits of the same time by sha, whatever order the pages came in', async () => {
    const same = (sha: string) => ({ ...apiCommit(5, sha), committed_at: '2026-10-01T00:00:00+00:00' })
    serve(0, { commits: [same('ccc'), apiCommit(1, 'zzz'), same('aaa'), same('bbb')] })
    const { result } = renderHook(() => useCommits('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.map((c) => c.sha)).toEqual(['aaa', 'bbb', 'ccc', 'zzz'])
  })

  it('the last sync time still comes with them', async () => {
    serve(5)
    const { result } = renderHook(() => useCommitsLastSync('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toBe('2026-10-01T10:00:00+00:00')
  })
})
