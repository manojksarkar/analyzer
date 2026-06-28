import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useProjects } from '../useProjects'

// End-to-end harness proof: hook → api → http → (MSW intercepts) → mapper.
// MSW serves src/test/fixtures/projects.json, so no backend is needed.
function makeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

describe('useProjects', () => {
  it('fetches projects and maps them to the camelCase FE shape', async () => {
    const { result } = renderHook(() => useProjects(), { wrapper: makeWrapper() })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    const first = result.current.data?.[0]
    expect(first?.name).toBe('Brake Control Unit')
    // `standard` is the mapped/humanised compliance_standard — proves the mapper ran.
    expect(first?.standard).toBe('ISO 26262')
    expect(first?.repoPath).toContain('github.com')
  })
})
