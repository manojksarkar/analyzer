import { describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { emptyReview } from '../../../test/factories'
import { groupDocsByProcess } from '../../../lib/docTree'
import type { Document } from '../../../types'
import { DocTreePanel } from '../DocTreePanel'

/* #44: the reader's document list by keyboard -- every document a button in reading order (Tab
   walks it), the open one marked as the current page, a group says whether it is open, and the
   reviewer menu closes on Esc, back to its button. */

const mk = (id: string, name: string, process: string, layer: string): Document => ({
  id, name, process, layer, group: name, status: 'in_review', version: 'v1.2.0', versionId: 'ver3',
  updatedAt: '2026-10-01T09:00:00Z', reviewer: null, review: emptyReview,
})
// SWE.3 across two layers (groups, sub-grouped by layer), and one SWE.4.
const docs = [
  mk('d1', 'Math', 'SWE.3', 'Layer1'), mk('d2', 'Gpio', 'SWE.3', 'Layer2'), mk('d3', 'Math', 'SWE.4', 'Layer1'),
]

function setup() {
  const onOpenDoc = vi.fn()
  render(
    <DocTreePanel
      groups={groupDocsByProcess(docs)}
      assigneeOptions={[{ value: 'u2', label: 'Bob Kumar' }]}
      effectiveAssignee=""
      meId="u1"
      isDeveloper={false}
      activeDocId={docs[0].id}
      onPickAssignee={() => {}}
      onOpenDoc={onOpenDoc}
      onFold={() => {}}
    />,
  )
  return { onOpenDoc, user: userEvent.setup() }
}

describe('DocTreePanel by keyboard', () => {
  it('Tab reaches the documents; the open one is the current page, a group says it is open', async () => {
    const { onOpenDoc, user } = setup()
    const nav = screen.getByRole('navigation', { name: 'Documents of this version' })
    const current = within(nav).getAllByRole('button').find((b) => b.getAttribute('aria-current') === 'page')
    expect(current).toBeDefined()
    expect(within(nav).getAllByRole('button').filter((b) => b.hasAttribute('aria-expanded')).length).toBeGreaterThan(0)
    // Tab from the reviewer filter walks into the tree, and Enter opens a document.
    screen.getByRole('button', { name: 'Reviewer filter: Reviewer' }).focus()
    let guard = 0
    while (!(document.activeElement && nav.contains(document.activeElement) && document.activeElement.getAttribute('title')) && guard++ < 20) {
      await user.tab()
    }
    expect(nav).toContainElement(document.activeElement as HTMLElement)
    await user.keyboard('{Enter}')
    expect(onOpenDoc).toHaveBeenCalled()
  })

  it('the reviewer menu says it is open, and Esc closes it back to its button', async () => {
    const { user } = setup()
    const trigger = screen.getByRole('button', { name: 'Reviewer filter: Reviewer' })
    await user.click(trigger)
    expect(trigger).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: 'Bob Kumar' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    expect(screen.queryByRole('button', { name: 'Bob Kumar' })).toBeNull()
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(trigger).toHaveFocus()
  })

  it('an Esc in a box elsewhere closes the menu but leaves focus in the box', async () => {
    const { user } = setup()
    const box = document.body.appendChild(document.createElement('textarea'))
    try {
      await user.click(screen.getByRole('button', { name: 'Reviewer filter: Reviewer' }))
      box.focus()
      await user.keyboard('{Escape}')
      expect(screen.queryByRole('button', { name: 'Bob Kumar' })).toBeNull()
      expect(box).toHaveFocus()
    } finally {
      box.remove()
    }
  })
})
