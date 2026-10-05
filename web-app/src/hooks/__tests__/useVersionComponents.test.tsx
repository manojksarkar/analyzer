import { createElement, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { act, renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { projectKeys } from '../useProjects'
import { runsPollMs, useGenerateComponents } from '../useVersionComponents'
import type { ProjectRun } from '../../types'

/* The Overview's runs were read again only while one was alive: a run started from the command
   line after the page loaded never showed, and a "Stopped" card stayed after its resume. */

describe('the project runs', () => {
  it('are read again every 15 s while one is alive, and every minute otherwise', () => {
    expect(runsPollMs([{ alive: true } as ProjectRun])).toBe(15_000)
    expect(runsPollMs([{ alive: false } as ProjectRun])).toBe(60_000)
    expect(runsPollMs([])).toBe(60_000)
    expect(runsPollMs(undefined)).toBe(60_000)
  })

  it('are read again when Generate starts a run', async () => {
    server.use(http.post(`${API_BASE_URL}/projects/p1/versions/ver1/documents/generate`, () =>
      HttpResponse.json({ job_id: 'j1', status: 'queued', version_id: 'ver1', components: ['Layer1.A'], skipped: [] }, { status: 202 })))
    const client = new QueryClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
    const { result } = renderHook(() => useGenerateComponents('p1', 'ver1'), { wrapper })
    await act(async () => { await result.current.mutateAsync(['Layer1.A']) })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.runs('p1') })
  })
})
