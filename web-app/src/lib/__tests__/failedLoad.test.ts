import { describe, expect, it, vi } from 'vitest'
import { failedLoad, type LoadResult } from '../failedLoad'

const q = (over: Partial<LoadResult> = {}): LoadResult => ({
  isError: false, error: null, data: undefined, isFetching: false, refetch: vi.fn(async () => undefined), ...over,
})

describe('failedLoad', () => {
  it('nothing failed, or still loading: no failure', () => {
    expect(failedLoad(q({ data: [] }), q())).toBeNull()
  })

  it('a failed read with nothing to show is a failure: its error, and Retry reads the failed ones again', () => {
    const ok = q({ data: [] })
    const bad = q({ isError: true, error: new Error('Server error') })
    const f = failedLoad(ok, bad)
    expect(f?.error).toEqual(new Error('Server error'))
    expect(f?.retrying).toBe(false)
    f?.retry()
    expect(bad.refetch).toHaveBeenCalledOnce()
    expect(ok.refetch).not.toHaveBeenCalled()
  })

  it('a background refetch that failed keeps showing what it had', () => {
    expect(failedLoad(q({ isError: true, error: new Error('x'), data: [1] }))).toBeNull()
  })

  it('says when a retry is under way', () => {
    expect(failedLoad(q({ isError: true, error: new Error('x'), isFetching: true }))?.retrying).toBe(true)
  })
})
