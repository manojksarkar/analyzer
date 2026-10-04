import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { FlowchartFigure } from '../components/FlowchartFigure'
import type { FlowchartEntry } from '../../../types'

const drawn: FlowchartEntry = {
  label: 'int add(int a, int b)', status: 'drawn', imageUrl: 'http://api/x/Math_add.svg',
  width: 400, height: 200, boxes: 7, flowchartId: null, editable: false,
}

describe('FlowchartFigure', () => {
  it('shows a drawn chart as a lazy image in space reserved from its size', () => {
    render(<FlowchartFigure chart={drawn} />)
    const img = screen.getByRole('img', { name: 'Flowchart of int add(int a, int b)' })
    expect(img).toHaveAttribute('src', 'http://api/x/Math_add.svg')
    expect(img).toHaveAttribute('loading', 'lazy')
    expect(img).toHaveAttribute('width', '400')
    expect(img).toHaveAttribute('height', '200')
  })

  it('opens the chart full screen', async () => {
    render(<FlowchartFigure chart={drawn} />)
    await userEvent.click(screen.getByRole('button', { name: /open the flowchart of int add/i }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('int add(int a, int b)')
    expect(dialog).toHaveTextContent('7 boxes')
    expect(screen.getByRole('button', { name: 'Zoom in' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Fit' })).toBeInTheDocument()
  })

  it('says a chart over the limit is too large, with no image', () => {
    render(<FlowchartFigure chart={{ ...drawn, status: 'too_large', imageUrl: null, boxes: 612 }} />)
    expect(screen.getByText('Too large to draw (612 boxes)')).toBeInTheDocument()
    expect(screen.queryByRole('img', { name: /flowchart of/i })).toBeNull()
  })

  it('says a chart without a picture was not drawn for this run -- never shows its source', () => {
    render(<FlowchartFigure chart={{ ...drawn, status: 'missing', imageUrl: null }} />)
    expect(screen.getByText('Flowchart not drawn for this run')).toBeInTheDocument()
    expect(screen.queryByText(/digraph/)).toBeNull()
  })
})

/* #27: a very tall flowchart fits the reading column as a narrow picture no taller than 480 px
   (it was a column-wide box with a sliver in it), and opens full size. #44: the viewer works
   from the keyboard -- + and - zoom, 0 fits, the arrows move, Esc closes. */
describe('FlowchartFigure in the reading column, and its viewer by keyboard', () => {
  const RO = globalThis.ResizeObserver
  beforeEach(() => {
    // jsdom has no layout: the viewer's box is 1000 x 800.
    globalThis.ResizeObserver = class {
      cb: ResizeObserverCallback
      constructor(cb: ResizeObserverCallback) { this.cb = cb }
      observe() { this.cb([{ contentRect: { width: 1000, height: 800 } } as ResizeObserverEntry], this as never) }
      unobserve() {}
      disconnect() {}
    } as unknown as typeof ResizeObserver
  })
  afterEach(() => { globalThis.ResizeObserver = RO })

  it('draws a tall chart narrow, no taller than 480 px, in space reserved for it', () => {
    render(<FlowchartFigure chart={{ ...drawn, width: 10_000, height: 37_000 }} />)
    const img = screen.getByRole('img', { name: /Flowchart of/ })
    expect(img).toHaveAttribute('height', '480')
    expect(img).toHaveAttribute('width', '130')
    expect(img).toHaveClass('max-w-full', 'h-auto')
  })

  it('zooms, fits and moves by keyboard, and Esc closes it', async () => {
    render(<FlowchartFigure chart={{ ...drawn, width: 400, height: 900 }} />)
    await userEvent.click(screen.getByRole('button', { name: /open the flowchart/i }))
    const dialog = screen.getByRole('dialog')
    expect(dialog).toHaveTextContent('84%')
    fireEvent.keyDown(window, { key: '+' })
    await waitFor(() => expect(dialog).toHaveTextContent('104%'))
    fireEvent.keyDown(window, { key: '0' })
    await waitFor(() => expect(dialog).toHaveTextContent('84%'))
    const img = screen.getAllByRole('img', { name: /Flowchart of/ }).at(-1) as HTMLElement
    const before = img.style.transform
    fireEvent.keyDown(window, { key: 'ArrowDown' })
    await waitFor(() => expect(img.style.transform).not.toBe(before))
    await userEvent.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })
})
