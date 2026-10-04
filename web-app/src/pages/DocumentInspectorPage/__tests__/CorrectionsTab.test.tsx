import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { CorrectionsTab, type OrphanActions } from '../components/CorrectionsTab'
import { QueuedList } from '../components/QueuedList'
import type { Slot } from '../../../types'

/* The Corrections tab: corrections in force, undone ones the Word file still carries (R9 counts
   them until a re-export), orphans — which an admin may discard (R12) — and this document's
   queue for the next run (R10). */

const slot = (key: string, over: Partial<Slot> = {}): Slot => ({
  kind: 'description', key, text: 'Adds.', llmText: 'Adds.', humanText: null, isOverridden: false,
  isOrphaned: false, canUndo: false, updatedBy: 'u1', updatedAt: '2026-10-01T09:00:00Z', ...over,
})
const fixed = slot('C|U|add|int', { isOverridden: true, canUndo: true, text: 'Adds two.', humanText: 'Adds two.' })
const undone = slot('C|U|sub|int', { isOverridden: true, humanText: 'Adds.', text: 'Subtracts.', llmText: 'Subtracts.' })
const orphan = slot('C|U|gone|int', { isOrphaned: true, humanText: 'Old words.' })

function tab(over: { undone?: Slot[]; orphanActions?: OrphanActions } = {}) {
  render(
    <CorrectionsTab inForce={[fixed]} undone={over.undone} orphans={[orphan]} isLoading={false} isError={false}
      userName={() => 'Alice'} onJump={vi.fn()} orphanActions={over.orphanActions} />,
  )
}

afterEach(() => vi.restoreAllMocks())

describe('CorrectionsTab', () => {
  it('lists undone corrections apart while the Word file still has them', () => {
    tab({ undone: [undone] })
    const section = screen.getByRole('region', { name: 'Undone corrections' })
    expect(within(section).getByText('Undone — not in the Word file yet (1)')).toBeInTheDocument()
    expect(within(section).getByText('Subtracts.')).toBeInTheDocument()
    expect(within(section).getByText(/the Word file keeps the correction until a re-export/)).toBeInTheDocument()
  })

  it('no undone section when there are none to show (the Word file is up to date)', () => {
    tab()
    expect(screen.queryByRole('region', { name: 'Undone corrections' })).toBeNull()
  })

  it('no Discard for anyone but an admin', () => {
    tab()
    expect(screen.queryByRole('button', { name: /Discard/ })).toBeNull()
  })

  it('an admin discards one orphan, or all of the version, after a confirm that says it is final', async () => {
    const actions: OrphanActions = { discard: vi.fn(), discardAll: vi.fn(), versionCount: 4, busy: false }
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValue(true)
    tab({ orphanActions: actions })
    const one = screen.getByRole('button', { name: 'Discard the orphaned correction of gone' })
    await userEvent.click(one)
    expect(actions.discard).not.toHaveBeenCalled()
    await userEvent.click(one)
    expect(actions.discard).toHaveBeenCalledWith(orphan)
    await userEvent.click(screen.getByRole('button', { name: 'Discard all orphans' }))
    expect(confirm).toHaveBeenLastCalledWith(expect.stringMatching(
      /^Discard all 4 orphaned corrections of this version\? This cannot be undone, and later versions will not carry them\.$/))
    expect(actions.discardAll).toHaveBeenCalled()
  })
})

describe('QueuedList (R10)', () => {
  it('lists this document’s queued texts, and counts the version’s others', async () => {
    const pending = (key: string) => ({
      slotKind: 'description', slotKey: key, reason: `rewrite ${key}`,
      causedBy: { slotKind: 'description', slotKey: 'C|U|add|int' }, requestedAt: null,
    })
    server.use(
      http.get(`${API_BASE_URL}/projects/p1/versions/v1/regeneration-queue`, () => HttpResponse.json({
        pending: [pending('C|U|sub|int'), pending('Other|X|f|'), pending('Other|X|g|')], total: 3,
      })),
    )
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <QueuedList projectId="p1" versionId="v1" slotRefs={new Set(['description:C|U|sub|int', 'description:C|U|add|int'])} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('rewrite C|U|sub|int')).toBeInTheDocument()
    expect(screen.queryByText('rewrite Other|X|f|')).toBeNull()
    expect(screen.getByText('Queued for the next run (1)')).toBeInTheDocument()
    expect(screen.getByText('2 more in other documents of this version.')).toBeInTheDocument()
  })

  it('matches a queued text by its kind and key: a description and a behaviour name share a key', async () => {
    const pending = (kind: string) => ({
      slotKind: kind, slotKey: 'C|U|sub|int', reason: `rewrite the ${kind}`, causedBy: null, requestedAt: null,
    })
    server.use(
      http.get(`${API_BASE_URL}/projects/p1/versions/v1/regeneration-queue`, () => HttpResponse.json({
        pending: [pending('description'), pending('behaviourInputName')], total: 2,
      })),
    )
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <QueuedList projectId="p1" versionId="v1" slotRefs={new Set(['description:C|U|sub|int'])} />
      </QueryClientProvider>,
    )
    expect(await screen.findByText('rewrite the description')).toBeInTheDocument()
    expect(screen.queryByText('rewrite the behaviourInputName')).toBeNull()
    expect(screen.getByText('1 more in other documents of this version.')).toBeInTheDocument()
  })
})
