import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoadError } from '../LoadError'

/* A failed read says what failed, with the server's message, and offers Retry. */

describe('LoadError', () => {
  it.each([false, true])('shows the message and retries (compact: %s)', async (compact) => {
    const onRetry = vi.fn()
    render(<LoadError what="the documents" error={new Error('Server error (500)')} onRetry={onRetry} compact={compact} />)
    const alert = screen.getByRole('alert')
    expect(alert).toHaveTextContent('Could not load the documents')
    expect(alert).toHaveTextContent('Server error (500)')
    await userEvent.setup().click(screen.getByRole('button', { name: /Retry/ }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('an error with no message still says something', () => {
    render(<LoadError what="the comparison" error={undefined} onRetry={() => {}} />)
    expect(screen.getByRole('alert')).toHaveTextContent('The server did not answer.')
  })

  it('Retry is busy while a retry runs', () => {
    render(<LoadError what="x" error={new Error('e')} onRetry={() => {}} retrying />)
    expect(screen.getByRole('button', { name: /Retry/ })).toBeDisabled()
  })
})
