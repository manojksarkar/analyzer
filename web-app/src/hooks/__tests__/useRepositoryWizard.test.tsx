import { useEffect, useState } from 'react'
import { describe, expect, it } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { API_BASE_URL } from '../../lib/http'
import { useRepositoryWizard } from '../useRepositoryWizard'

/* The wizard's "Add member" search lists the hook's object in its effect's dependencies. A new
   object each render re-ran the search after every answer: GET /users/search without end. */

describe('useRepositoryWizard', () => {
  it('is the same object on every render', () => {
    const { result, rerender } = renderHook(() => useRepositoryWizard())
    const first = result.current
    rerender()
    expect(result.current).toBe(first)
  })

  it('a search in an effect on it asks the directory once, not after every answer', async () => {
    let calls = 0
    server.use(http.get(`${API_BASE_URL}/users/search`, () => {
      calls += 1
      return HttpResponse.json({ users: [{ id: 'u1', name: 'Dev', email: 'dev@x', initials: 'D' }] })
    }))
    renderHook(() => {
      const repo = useRepositoryWizard()
      const [, setFound] = useState<unknown[]>([])
      useEffect(() => {
        let active = true
        const t = window.setTimeout(async () => {
          const users = await repo.searchUsers('')
          if (active) setFound(users)              // a new array: the page renders again
        }, 10)
        return () => { active = false; window.clearTimeout(t) }
      }, [repo])
    })
    await waitFor(() => expect(calls).toBe(1))
    await new Promise((r) => setTimeout(r, 300))
    expect(calls).toBe(1)
  })
})
