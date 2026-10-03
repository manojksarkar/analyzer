import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from '../StatusBadge'

describe('StatusBadge', () => {
  it('shows the one word for each document state', () => {
    const { rerender } = render(<StatusBadge status="submitted" />)
    expect(screen.getByText('Ready for approval')).toBeInTheDocument()
    rerender(<StatusBadge status="changes_requested" />)
    expect(screen.getByText('Changes requested')).toBeInTheDocument()
    rerender(<StatusBadge status="approved" />)
    expect(screen.getByText('Approved')).toBeInTheDocument()
    rerender(<StatusBadge status="in_review" />)
    expect(screen.getByText('In review')).toBeInTheDocument()
  })
  it('takes a derived label and a suffix', () => {
    render(<StatusBadge status="in_review" label="In review · 3/6 approved" />)
    expect(screen.getByText('In review · 3/6 approved')).toBeInTheDocument()
    const { container } = render(<StatusBadge status="approved" suffix=" · from v1.1.0" />)
    expect(container.textContent).toContain('Approved · from v1.1.0')
  })
  it('colours each state its own way', () => {
    const { container: a } = render(<StatusBadge status="approved" />)
    const { container: b } = render(<StatusBadge status="changes_requested" />)
    expect((a.firstChild as HTMLElement).className).not.toBe((b.firstChild as HTMLElement).className)
  })
})
