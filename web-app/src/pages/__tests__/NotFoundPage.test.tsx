import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { NotFoundPage } from '../NotFoundPage'

/* An unknown address went to Projects without a word; it says so now, with a way back. */

describe('NotFoundPage', () => {
  it('says the page is not found and links back to the projects', () => {
    render(<MemoryRouter initialEntries={['/projects/p1/nowhere']}><NotFoundPage /></MemoryRouter>)
    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(screen.getByText(/\/projects\/p1\/nowhere/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Back to projects/ })).toHaveAttribute('href', '/projects')
  })
})
