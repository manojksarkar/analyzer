import { afterEach, describe, expect, it, vi } from 'vitest'
import { toast, useToastStore } from '../Toast'

/* Over plain http (the office server) the page is not a secure context: `crypto.randomUUID` is
   undefined there, and a toast must still show. */

describe('toast', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    useToastStore.setState({ toasts: [] })
  })

  it('works without crypto.randomUUID, each toast with its own id', () => {
    vi.stubGlobal('crypto', {})
    expect(() => {
      toast.success('Saved')
      toast.error('Approve failed', 'STALE_EXPORT')
      toast.info('Re-export queued')
    }).not.toThrow()
    const { toasts } = useToastStore.getState()
    expect(toasts.map((t) => t.title)).toEqual(['Saved', 'Approve failed', 'Re-export queued'])
    expect(new Set(toasts.map((t) => t.id)).size).toBe(3)
  })

  it('dismiss removes only the toast named', () => {
    toast.info('One')
    toast.info('Two')
    const [first, second] = useToastStore.getState().toasts
    useToastStore.getState().dismiss(first.id)
    expect(useToastStore.getState().toasts).toEqual([second])
  })
})
