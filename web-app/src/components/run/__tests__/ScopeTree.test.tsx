import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ScopeTree } from '../ScopeTree'
import type { ArchLayer } from '../../../types'

/* Accessibility: the tree's checkboxes are its controls. They were pictures of checkboxes (out of
   the Tab order, read-only) inside a clickable box, so the keyboard could tick nothing but All /
   None. The row's click stays, as a larger target for the same checkbox. */
const LAYERS = [
  { name: 'Layer1', groups: [{ name: 'Core', components: [{ name: 'Alpha' }, { name: 'Beta' }] }] },
] as unknown as ArchLayer[]

describe('ScopeTree: keyboard', () => {
  it('ticks from the keyboard: the checkbox takes the focus, Space ticks it', async () => {
    const onChange = vi.fn()
    render(<ScopeTree layers={LAYERS} ticked={new Set()} onChange={onChange} />)
    const layer = screen.getByRole('checkbox', { name: 'Layer1' })
    expect(layer).not.toHaveAttribute('tabindex', '-1')
    expect(layer).not.toHaveAttribute('aria-hidden')
    layer.focus()
    await userEvent.setup().keyboard(' ')
    expect(onChange).toHaveBeenCalledTimes(1)
    expect([...onChange.mock.calls[0][0]]).toHaveLength(2)          // both of the layer's components
  })

  it('a click on the checkbox ticks once: the row does not tick it again', async () => {
    const onChange = vi.fn()
    render(<ScopeTree layers={LAYERS} ticked={new Set()} onChange={onChange} />)
    await userEvent.setup().click(screen.getByRole('checkbox', { name: 'Layer1' }))
    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('a fold arrow says what it folds and whether it is open', () => {
    render(<ScopeTree layers={LAYERS} ticked={new Set()} onChange={() => {}} />)
    expect(screen.getByRole('button', { name: 'Collapse Layer1' })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: 'Expand Core' })).toHaveAttribute('aria-expanded', 'false')
  })
})
