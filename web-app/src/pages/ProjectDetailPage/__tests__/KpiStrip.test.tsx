import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor, within } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { KpiStrip } from '../components/ReviewCards'
import type { Document, Version } from '../../../types'

/* The Overview's approval card: a gauge as the mockups' (light and dark) -- one arc per state with a
   gap between, "N / OF M APPROVED" in the middle counting up, and a legend with a bar per state. */

const doc = (id: string, status: Document['status']) =>
  ({ id, status, process: 'SWE.3', reviewer: null, title: id }) as unknown as Document

function mount(documents: Document[]) {
  const qc = new QueryClient()
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <KpiStrip documents={documents} version={{ tag: 'v1.2.0' } as Version} isAdmin meId="u1" />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const DOCS = [doc('a', 'approved'), doc('b', 'approved'), doc('c', 'submitted'), doc('d', 'in_review')]

describe('the approval gauge', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('one arc per state that has documents, a gap taken out of each', () => {
    const { container } = mount(DOCS)
    expect(screen.getByRole('img', { name: '2 of 4 approved' })).toBeInTheDocument()
    expect(screen.getByText('OF 4 APPROVED')).toBeInTheDocument()
    const arcs = [...container.querySelectorAll('g[data-state]')].map((g) => g.getAttribute('data-state'))
    expect(arcs).toEqual(['approved', 'submitted', 'in_review'])          // none for changes requested
    const approved = container.querySelector('g[data-state="approved"] .gauge-arc')!
    const C = 2 * Math.PI * 52
    expect(approved.getAttribute('stroke-dasharray')).toBe(`${(C / 2 - 12).toFixed(2)} ${C.toFixed(2)}`)
    // drawn in by CSS: it starts hidden, its offset its own length
    expect(approved.getAttribute('stroke-dashoffset')).toBe((C / 2 - 12).toFixed(2))
  })

  it('a single state is a whole ring, no gap', () => {
    const { container } = mount([doc('a', 'approved'), doc('b', 'approved')])
    const C = 2 * Math.PI * 52
    expect(container.querySelector('.gauge-arc')!.getAttribute('stroke-dasharray')).toBe(`${C.toFixed(2)} ${C.toFixed(2)}`)
  })

  it('the legend gives each state its count, share and bar', () => {
    const { container } = mount(DOCS)
    const row = screen.getByText('Approved').closest('div')!.parentElement!.parentElement!
    expect(within(row).getByText('2')).toBeInTheDocument()
    expect(within(row).getByText('50%')).toBeInTheDocument()
    const bars = [...container.querySelectorAll<HTMLElement>('.gauge-bar-fill')].map((b) => b.style.width)
    expect(bars).toEqual(['50%', '25%', '0%', '25%'])
  })

  it('the number counts up when motion is allowed', async () => {
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: false, media: q, addEventListener() {}, removeEventListener() {} }))
    mount(DOCS)
    const n = () => screen.getByRole('img', { name: '2 of 4 approved' }).querySelector('text')!.textContent
    expect(n()).toBe('0')
    await waitFor(() => expect(n()).toBe('2'))
  })
})
