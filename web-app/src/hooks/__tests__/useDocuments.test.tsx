import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { useDocuments } from '../useProjects'

/* The documents route answers at most 100 a page; a version of the office project has about 240
   (3 layers × 40 components × SWE.3 and SWE.4). The lists, KPIs, approval bar and bulk approve
   count what useDocuments returns, so it must return every page. */

const apiDoc = (i: number) => ({
  id: `doc${i}`, name: `Comp${i}`, subtitle: '', process: i % 2 ? 'SWE.4' : 'SWE.3',
  layer: 'Layer1', group: `Comp${i}`, status: 'in_review', version_id: 'ver1', due_date: null,
  assignees: [], reviewer: null,
  review: {
    comment: null, changes_comment: null, approved_by: null, approved_at: null,
    approval_comment: null, docx_sha256: null, carried_from: null, last_event: null,
  },
  created_at: '2026-10-01T00:00:00Z', updated_at: '2026-10-01T00:00:00Z',
})

/** A version of `count` documents, served the way the API pages them. */
function serve(count: number, { withTotal = true } = {}) {
  const all = Array.from({ length: count }, (_, i) => apiDoc(i + 1))
  const asked: { page: number; perPage: number; versionId: string | null }[] = []
  server.use(
    http.get(`${API_BASE_URL}/projects/p1/documents`, ({ request }) => {
      const url = new URL(request.url)
      const page = Number(url.searchParams.get('page') ?? 1)
      const perPage = Math.min(Number(url.searchParams.get('per_page') ?? 20), 100)
      asked.push({ page, perPage, versionId: url.searchParams.get('version_id') })
      const documents = all.slice((page - 1) * perPage, page * perPage)
      return HttpResponse.json({
        documents,
        ...(withTotal ? { pagination: { page, per_page: perPage, total: all.length } } : {}),
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

describe('useDocuments', () => {
  it("returns every document of the version, not the first page's 100", async () => {
    const asked = serve(240)
    const { result } = renderHook(() => useDocuments('p1', { versionId: 'ver1' }), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(240)
    expect(new Set(result.current.data?.map((d) => d.id)).size).toBe(240)
    expect(asked.map((a) => a.page).sort((a, b) => a - b)).toEqual([1, 2, 3])
    expect(asked.every((a) => a.perPage === 100 && a.versionId === 'ver1')).toBe(true)
  })

  it('reads one page when there are 100 or fewer', async () => {
    const asked = serve(57)
    const { result } = renderHook(() => useDocuments('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(57)
    expect(asked).toHaveLength(1)
  })

  it('reads on until a short page when the API does not say the total', async () => {
    const asked = serve(230, { withTotal: false })
    const { result } = renderHook(() => useDocuments('p1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toHaveLength(230)
    expect(asked.map((a) => a.page)).toEqual([1, 2, 3])
  })

  it('a caller that names a page gets that page', async () => {
    const asked = serve(240)
    const { result } = renderHook(() => useDocuments('p1', { page: 2, perPage: 50 }), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data?.map((d) => d.id)[0]).toBe('doc51')
    expect(result.current.data).toHaveLength(50)
    expect(asked).toEqual([{ page: 2, perPage: 50, versionId: null }])
  })
})
