import { useEffect } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ErrorBoundary } from '../ErrorBoundary'

/* The project layout's boundary outlives navigation: one crash kept the error screen on every
   page after it. Its reset key is the location — a new one clears the error. */

function Page({ explode, name }: { explode: boolean; name: string }) {
  if (explode) throw new Error('kaboom')
  return <p>{name}</p>
}

describe('ErrorBoundary resetKey', () => {
  beforeEach(() => { vi.spyOn(console, 'error').mockImplementation(() => {}) })
  afterEach(() => { vi.restoreAllMocks() })

  it('keeps the error on the same location, and clears it on another', () => {
    const { rerender } = render(
      <ErrorBoundary resetKey="/projects/p1/overview"><Page explode name="overview" /></ErrorBoundary>)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()
    expect(screen.getByText('kaboom')).toBeInTheDocument()

    rerender(<ErrorBoundary resetKey="/projects/p1/overview"><Page explode={false} name="overview" /></ErrorBoundary>)
    expect(screen.getByText('Something went wrong')).toBeInTheDocument()

    rerender(<ErrorBoundary resetKey="/projects/p1/documents"><Page explode={false} name="documents" /></ErrorBoundary>)
    expect(screen.queryByText('Something went wrong')).not.toBeInTheDocument()
    expect(screen.getByText('documents')).toBeInTheDocument()
  })

  it('a healthy page is not remounted when the location changes', () => {
    const mounted = vi.fn()
    function Counted() {
      useEffect(() => { mounted() }, [])
      return <p>page</p>
    }
    const { rerender } = render(<ErrorBoundary resetKey="/a"><Counted /></ErrorBoundary>)
    rerender(<ErrorBoundary resetKey="/b"><Counted /></ErrorBoundary>)
    expect(screen.getByText('page')).toBeInTheDocument()
    expect(mounted).toHaveBeenCalledTimes(1)
  })
})
