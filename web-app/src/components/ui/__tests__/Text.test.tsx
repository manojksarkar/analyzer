import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Text } from '../Text'

// Smoke test proving the jsdom + Testing Library harness renders our components.
describe('Text', () => {
  it('renders its children', () => {
    render(<Text>Hello</Text>)
    expect(screen.getByText('Hello')).toBeInTheDocument()
  })

  it('applies the variant class', () => {
    render(<Text variant="title">Titled</Text>)
    expect(screen.getByText('Titled').className).toContain('font-semibold')
  })
})
