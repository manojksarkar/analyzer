import type { ReactNode } from 'react'
import { afterEach, describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { liveSelection } from '../../lib/selection'
import { useUIStore } from '../../store/ui'
import project from '../../test/fixtures/captured/project.json'
import commits from '../../test/fixtures/captured/commits.json'
import versions from '../../test/fixtures/captured/versions.json'
import { useProjectViewState } from '../useProjectViewState'
import type { Version } from '../../types'

/* A Subbar pick naming a version that is gone — a cancelled run's draft — is no pick: the default
   version shows. It resolved to no version, and the pages read every version's documents. */

const v = (id: string) => ({ id }) as Version

describe('liveSelection', () => {
  it('drops a pick of a version that is not there, once the versions are known', () => {
    const gone = { type: 'version', id: 'verGone' } as const
    expect(liveSelection(gone, [v('ver3'), v('ver2')])).toBeUndefined()
    expect(liveSelection(gone, undefined)).toBe(gone)
  })

  it('keeps a pick of a version that is there, and any commit pick', () => {
    const there = { type: 'version', id: 'ver2' } as const
    const commit = { type: 'commit', sha: 'abc1234' } as const
    expect(liveSelection(there, [v('ver3'), v('ver2')])).toBe(there)
    expect(liveSelection(commit, [v('ver3')])).toBe(commit)
    expect(liveSelection(undefined, [v('ver3')])).toBeUndefined()
  })
})

describe('useProjectViewState', () => {
  afterEach(() => useUIStore.setState({ selectedRef: {} }))

  function mount() {
    server.use(
      http.get(`${API_BASE_URL}/projects/p1`, () => HttpResponse.json(project)),
      http.get(`${API_BASE_URL}/projects/p1/versions`, () => HttpResponse.json(versions)),
      http.get(`${API_BASE_URL}/projects/p1/commits`, () => HttpResponse.json(commits)),
      http.get(`${API_BASE_URL}/projects/p1/jobs/current`, () => HttpResponse.json({ job: null })),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    )
    return renderHook(() => useProjectViewState('p1'), { wrapper })
  }

  it('shows the default version when the picked one is gone', async () => {
    useUIStore.getState().setSelectedRef('p1', { type: 'version', id: 'verDeletedDraft' })
    const { result } = mount()
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.viewVersionId).toBe('ver3')
  })

  it('shows the picked version while it is there', async () => {
    useUIStore.getState().setSelectedRef('p1', { type: 'version', id: 'ver2' })
    const { result } = mount()
    await waitFor(() => expect(result.current.isLoading).toBe(false))
    expect(result.current.viewVersionId).toBe('ver2')
  })
})
