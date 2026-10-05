import { describe, expect, it } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import { BlocksPane } from '../components/DiffBlocks'
import { signColumns } from '../helpers'
import type { CompareBlock, DiffMark } from '../../../types'

/* #45: a diff told its added, removed and changed words and rows by colour alone. Each now says
   what it is: <ins>/<del> with a line under or through it, and its kind in words for a screen
   reader; a table row's change is a sign in a column of its own. */

describe('BlocksPane change marks', () => {
  it('marks added, removed and changed words beyond their colour', () => {
    const blocks: CompareBlock[] = [{
      kind: 'text',
      segments: [
        { text: 'Reads ', mark: 'none' },
        { text: 'speed', mark: 'add' },
        { text: 'rpm', mark: 'del' },
        { text: 'twice', mark: 'change' },
      ],
    }]
    const { container } = render(<BlocksPane blocks={blocks} emptyLabel="No content." />)
    expect(container.querySelector('ins')).toHaveTextContent('[added: speed]')
    expect(container.querySelector('ins')).toHaveClass('underline')
    expect(container.querySelector('del')).toHaveTextContent('[removed: rpm]')
    expect(screen.getByText('twice')).toHaveClass('decoration-dotted')
    expect(screen.getByText('[changed:', { exact: false })).toHaveClass('sr-only')
  })

  it('gives a table with changed rows a column of signs', () => {
    const blocks: CompareBlock[] = [{
      kind: 'table',
      headers: ['Id', 'Name'],
      rows: [['IF_1', 'init'], ['IF_2', 'run'], ['IF_3', 'stop'], ['IF_4', 'idle']],
      rowMarks: ['add', 'del', 'none', 'none'],
      cellMarks: [['none', 'none'], ['none', 'none'], ['none', 'change'], ['none', 'none']],
    }]
    render(<BlocksPane blocks={blocks} emptyLabel="No content." />)
    const rows = screen.getAllByRole('row')
    expect(within(rows[0]).getByText('Change')).toHaveClass('sr-only')
    expect(rows[1]).toHaveTextContent('+added')
    expect(rows[2]).toHaveTextContent('−removed')
    expect(rows[3]).toHaveTextContent('~changed')
    expect(within(rows[4]).getAllByRole('cell')[0]).toBeEmptyDOMElement()
  })

  it('adds no sign column to a table where nothing changed', () => {
    const blocks: CompareBlock[] = [{
      kind: 'table', headers: ['Id'], rows: [['IF_1']], rowMarks: ['none'], cellMarks: [['none']],
    }]
    render(<BlocksPane blocks={blocks} emptyLabel="No content." />)
    expect(screen.queryByText('Change')).not.toBeInTheDocument()
    expect(screen.getAllByRole('columnheader')).toHaveLength(1)
  })

  /* Review of cded9b4: each pane decided its own sign column, so a table whose rows were added
     (marked on the current side only) had one more column on that side; and the screen reader's
     "[added: …]" went into text copied from the page. */
  it('keeps the screen-reader words out of a copy', () => {
    const blocks: CompareBlock[] = [{ kind: 'text', segments: [{ text: 'speed', mark: 'add' }] }]
    render(<BlocksPane blocks={blocks} emptyLabel="No content." />)
    const said = screen.getAllByText(/^\[added:\s*$|^\]$/)
    expect(said).toHaveLength(2)
    for (const el of said) expect(el).toHaveClass('sr-only', 'select-none')
  })

  it('gives a table the same columns on both sides when only one side has changed rows', () => {
    const table = (rowMarks: DiffMark[]): CompareBlock => ({
      kind: 'table', headers: ['Id', 'Name'], rows: rowMarks.map((_, i) => [`IF_${i}`, 'x']), rowMarks,
      cellMarks: rowMarks.map(() => ['none', 'none']),
    })
    const baseline = [{ kind: 'text', segments: [{ text: 'T', mark: 'none' }] } as CompareBlock, table(['none'])]
    const current = [table(['none', 'add'])]
    const signs = signColumns(baseline, current)
    expect(signs).toEqual([true])
    const left = render(<BlocksPane blocks={baseline} signs={signs} emptyLabel="No content." />)
    expect(within(left.container).getAllByRole('columnheader')).toHaveLength(3)
    left.unmount()
    render(<BlocksPane blocks={current} signs={signs} emptyLabel="No content." />)
    expect(screen.getAllByRole('columnheader')).toHaveLength(3)
    // Alone, the reference side would have had no sign column.
    expect(signColumns(baseline)).toEqual([false])
  })
})
