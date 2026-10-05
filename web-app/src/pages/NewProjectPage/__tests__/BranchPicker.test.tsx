import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { BranchPicker } from '../components/BranchPicker'
import { matchBranches } from '../helpers'

/* Step 1's branch is ONE box to search and pick in: it shows the picked branch, opens every
   branch, filters as you type, picks with the arrows + Enter or a click; Esc and leaving the
   box keep the branch picked before. (It was a search field over a dropdown.) */

const BRANCHES = ['main', 'develop', 'release/v1.0', 'release/v1.1', 'release/v1.2', 'feature/can-stack', 'hotfix/watchdog-reset']

function setup(initial = 'main') {
  const onPick = vi.fn()
  function Page() {
    const [branch, setBranch] = useState(initial)
    return (
      <>
        <BranchPicker branches={BRANCHES} value={branch} defaultBranch="main"
          onPick={(b) => { onPick(b); setBranch(b) }} />
        <button type="button">Elsewhere</button>
      </>
    )
  }
  render(<Page />)
  return { onPick, user: userEvent.setup(), box: screen.getByRole('combobox', { name: 'Branch' }) }
}

const rows = () => within(screen.getByRole('listbox', { name: 'Branches' })).queryAllByRole('option')
const names = () => rows().map((r) => r.textContent?.replace(/default|check/g, ''))

describe('BranchPicker', () => {
  it('shows the picked branch; a click opens every branch, the picked one marked and the default tagged', async () => {
    const { box, user } = setup()
    expect(box).toHaveValue('main')
    expect(screen.queryByRole('listbox')).toBeNull()
    await user.click(box)
    expect(box).toHaveAttribute('aria-expanded', 'true')
    expect(rows()).toHaveLength(BRANCHES.length)
    const main = rows()[0]
    expect(main).toHaveAttribute('aria-selected', 'true')
    expect(main).toHaveTextContent('default')
    expect(box.getAttribute('aria-activedescendant')).toBe(main.id)
  })

  it('typing filters, says how many of how many, and Enter picks the first match', async () => {
    const { box, user, onPick } = setup()
    await user.click(box)
    await user.clear(box)
    await user.type(box, 'rel')
    expect(names()).toEqual(['release/v1.0', 'release/v1.1', 'release/v1.2'])
    expect(screen.getByText('3 of 7 branches')).toBeInTheDocument()
    await user.keyboard('{Enter}')
    expect(onPick).toHaveBeenCalledWith('release/v1.0')
    expect(box).toHaveValue('release/v1.0')
    expect(screen.queryByRole('listbox')).toBeNull()
  })

  it('the arrows move along the list, and Enter picks', async () => {
    const { box, user, onPick } = setup()
    await user.click(box)
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}')
    expect(onPick).toHaveBeenCalledWith('release/v1.0')
    // Closed, ↓ opens it again on the picked branch.
    await user.keyboard('{ArrowDown}')
    expect(rows().find((r) => r.id === box.getAttribute('aria-activedescendant'))).toHaveTextContent('release/v1.0')
  })

  it('no match says so', async () => {
    const { box, user } = setup()
    await user.click(box)
    await user.clear(box)
    await user.type(box, 'zzz')
    expect(rows()).toHaveLength(0)
    expect(screen.getByText('No branch matches “zzz”')).toBeInTheDocument()
  })

  it('Esc closes and keeps the branch picked before; what was typed is dropped', async () => {
    const { box, user, onPick } = setup()
    await user.click(box)
    await user.clear(box)
    await user.type(box, 'hot')
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(box).toHaveValue('main')
    expect(onPick).not.toHaveBeenCalled()
  })

  it('leaving the box keeps the branch picked before', async () => {
    const { box, user, onPick } = setup()
    await user.click(box)
    await user.clear(box)
    await user.type(box, 'dev')
    await user.click(screen.getByRole('button', { name: 'Elsewhere' }))
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(box).toHaveValue('main')
    expect(onPick).not.toHaveBeenCalled()
  })

  it('a click on a branch picks it; the branch already picked is not picked again', async () => {
    const { box, user, onPick } = setup()
    await user.click(box)
    await user.click(rows()[5])
    expect(onPick).toHaveBeenCalledWith('feature/can-stack')
    expect(box).toHaveValue('feature/can-stack')
    await user.click(box)
    await user.click(rows()[5])
    expect(onPick).toHaveBeenCalledTimes(1)
  })

  it('the chevron opens and closes the list, focus staying in the box', async () => {
    const { box, user } = setup()
    await user.click(screen.getByRole('button', { name: 'Open the branch list' }))
    expect(rows()).toHaveLength(BRANCHES.length)
    expect(box).toHaveFocus()
    await user.click(screen.getByRole('button', { name: 'Close the branch list' }))
    expect(screen.queryByRole('listbox')).toBeNull()
    expect(box).toHaveFocus()
  })
})

describe('matchBranches', () => {
  it('all for an empty query, else those containing it in any case', () => {
    expect(matchBranches(BRANCHES, '  ')).toEqual(BRANCHES)
    expect(matchBranches(BRANCHES, 'V1.1')).toEqual(['release/v1.1'])
    expect(matchBranches(BRANCHES, 'nothing')).toEqual([])
  })
})
