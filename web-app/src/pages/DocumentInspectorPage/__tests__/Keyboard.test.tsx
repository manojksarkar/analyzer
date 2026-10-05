import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { RichSection } from '../../../types'
import { RightPanel, type PanelTab } from '../components/RightPanel'
import { RichSectionView } from '../components/Sections'

/* #44 (the reader by keyboard): the right panel's tabs move with the arrows, as tabs do, and
   their content is their tab panel; a unit or behaviour diagram opens full size from the
   keyboard (#27: it fits the column in the page), and Esc closes it. */

const TABS: PanelTab[] = [{ id: 'outline', label: 'Outline' }, { id: 'review', label: 'Review' }, { id: 'corr', label: 'Corrections', count: 2 }]

function Panel() {
  const [active, setActive] = useState('outline')
  return (
    <RightPanel tabs={TABS} active={active} onTab={setActive} collapsed={false} onToggle={() => {}}>
      <p>{`content of ${active}`}</p>
    </RightPanel>
  )
}

describe('RightPanel by keyboard', () => {
  it('Tab reaches the selected tab; the arrows, Home and End move between tabs', async () => {
    const user = userEvent.setup()
    render(<Panel />)
    await user.tab()
    expect(screen.getByRole('tab', { name: 'Outline' })).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Review' })).toHaveFocus()
    expect(screen.getByRole('tab', { name: 'Review' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('tabpanel')).toHaveTextContent('content of review')
    await user.keyboard('{End}')
    expect(screen.getByRole('tab', { name: /Corrections/ })).toHaveFocus()
    await user.keyboard('{ArrowRight}')
    expect(screen.getByRole('tab', { name: 'Outline' })).toHaveFocus()
    // Only the selected tab is in the Tab order: the next Tab leaves the tab list.
    await user.tab()
    expect(screen.getByRole('button', { name: 'Collapse the panel' })).toHaveFocus()
  })
})

const diagram: RichSection = {
  id: 'unit-Math', number: '2.4', title: 'Math unit diagram', level: 2, type: 'diagram', content: null,
  table: null, imageUrl: 'https://assets/unit-Math.png', mermaid: null, children: [],
}

describe('a diagram of the document', () => {
  it('fits the column, and opens full size from the keyboard; Esc closes it', async () => {
    const user = userEvent.setup()
    render(<RichSectionView section={diagram} />)
    expect(screen.getByRole('img', { name: 'Math unit diagram' })).toHaveClass('w-full', 'max-h-[440px]', 'object-contain')
    await user.tab()
    expect(screen.getByRole('button', { name: 'Open Math unit diagram full size' })).toHaveFocus()
    await user.keyboard('{Enter}')
    expect(await screen.findByRole('dialog', { name: 'Math unit diagram' })).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
