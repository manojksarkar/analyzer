import { createElement, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '../../test/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { API_BASE_URL, ApiError } from '../../lib/http'
import type { ExportReadiness, Slot, SlotSaveResult } from '../../types'
import { projectKeys } from '../useProjects'
import {
  describeQueued, describeSave, isRegenerating, patchOverrides, saveErrorMessage, saveFailedNote,
  useDiscardOrphans, useReexportFinished, useReexportVersion, useSaveSlot, useVersionOverrides,
} from '../useReview'

/* Review & update: what the page says after a save, and after a save that failed
   (docs/spec/REVIEW_UPDATE_API_SPEC.md §5 "What a save did", §8 and §16 errors). */

const regenerating = new ApiError('The version is being regenerated.', 409, 'VERSION_REGENERATING')

describe('a refused save, in words', () => {
  it('a run regenerating the version: save again once it has finished, not a plain "try again"', () => {
    expect(isRegenerating(regenerating)).toBe(true)
    expect(saveErrorMessage(regenerating)).toBe(
      'A run is regenerating this version — nothing was saved. Save again once it has finished.')
    expect(saveErrorMessage(regenerating)).not.toMatch(/try again/)
  })
  it('an approved document keeps its message; any other 409 says what the server said', () => {
    expect(saveErrorMessage(new ApiError('x', 409, 'DOCUMENT_APPROVED'))).toMatch(/is approved, so it is locked/)
    const noGraph = new ApiError('the flowchart has no stored graph — re-derive the version', 409)
    expect(isRegenerating(noGraph)).toBe(false)
    expect(saveErrorMessage(noGraph)).toBe('the flowchart has no stored graph — re-derive the version')
  })
  it('under the box: a refusal (4xx) is not invited to retry; a fault (5xx, no answer) is', () => {
    const refused = saveFailedNote(new ApiError('text: must not contain the NUL character', 422))
    expect(refused).toBe('Not saved: text: must not contain the NUL character. Your text is still here.')
    expect(refused).not.toMatch(/retry/i)
    expect(saveFailedNote(regenerating)).toMatch(/Save again once it has finished/)
    expect(saveFailedNote(regenerating)).not.toMatch(/Leave the box again/)
    expect(saveFailedNote(new ApiError('Internal Server Error', 500))).toMatch(/Leave the box again to retry/)
    expect(saveFailedNote(new TypeError('Failed to fetch'))).toMatch(/Leave the box again to retry/)
  })
})

describe('what a save queued for the next run', () => {
  it('names each kind and its count when the answer names no text (the key is never taken apart)', () => {
    const queued = [
      { slotKind: 'description', slotKey: 'L1.App|AppMain|App_Start|void' },
      { slotKind: 'unitDescription', slotKey: 'L2.Gpio|GpioDrv' },
      { slotKind: 'description', slotKey: 'L1.App|AppMain|App_Stop|void' },
    ]
    expect(describeQueued(queued)).toBe('2 descriptions, 1 unit description')
    expect(describeSave({ previousText: null, queuedForRegeneration: queued }))
      .toBe('The next run rewrites 3 texts that depend on it: 2 descriptions, 1 unit description.')
  })
  it('names up to three texts when the answer carries their names', () => {
    const named = ['App_Start', 'App_Stop', 'App_Run', 'App_Idle'].map((n) => ({
      slotKind: 'description', slotKey: `k|${n}`, label: n,
    }))
    expect(describeQueued(named))
      .toBe('the description of App_Start, the description of App_Stop, the description of App_Run and 1 more')
  })
  it('says nothing of a queue when the save queued nothing', () => {
    expect(describeSave({ previousText: 'Old.', queuedForRegeneration: [] })).toBe('You replaced “Old.”.')
  })
})

const slotOf = (key: string, over: Partial<Slot> = {}): Slot => ({
  kind: 'description', key, text: 't', llmText: 'o', humanText: 't', isOverridden: true, isOrphaned: false,
  canUndo: true, updatedBy: 'u1', updatedAt: null, ...over,
})

describe('patchOverrides (R1 after a save, without reading every page again)', () => {
  it('replaces the saved slot by kind + key, first (newest first), without what the save did', () => {
    const old = [slotOf('A'), slotOf('B'), slotOf('B', { kind: 'unitDescription' })]
    const saved: SlotSaveResult = { ...slotOf('B', { text: 'new', humanText: 'new' }),
      previousText: 't', firstEdit: false, queuedForRegeneration: [] }
    const next = patchOverrides(old, [saved]) ?? []
    expect(next.map((s) => `${s.kind}:${s.key}:${s.text}`))
      .toEqual(['description:B:new', 'description:A:t', 'unitDescription:B:t'])
    expect(next[0]).not.toHaveProperty('previousText')
    expect(next[0]).not.toHaveProperty('queuedForRegeneration')
  })
  it('adds a slot not listed yet (its first correction), and leaves an unread cache alone', () => {
    expect(patchOverrides([slotOf('A')], [slotOf('N')])?.map((s) => s.key)).toEqual(['N', 'A'])
    expect(patchOverrides(undefined, [slotOf('N')])).toBeUndefined()
  })
})

describe('useReexportFinished', () => {
  it('when a re-export ends, reads the documents and the version’s review reads (R9, R10, R1) again', () => {
    const client = new QueryClient()
    const spy = vi.spyOn(client, 'invalidateQueries')
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
    const r9 = (status: string): ExportReadiness => ({
      stale: false, explanation: null, overrideCount: 0, pendingRenders: 0, failedRenders: 0,
      reexport: { jobId: 'j1', status, startedAt: null, completedAt: null, errorMessage: null },
    })
    const { rerender } = renderHook(({ r }) => useReexportFinished('p1', 'v1', r), { wrapper, initialProps: { r: r9('running') } })
    expect(spy).not.toHaveBeenCalled()
    rerender({ r: r9('complete') })
    expect(spy).toHaveBeenCalledWith({ queryKey: ['projects', 'p1', 'documents'] })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.review('p1', 'v1') })
  })
})

/* Review findings on 6c5863b: a discard left the edit boxes' orphan notes (the renders were not
   read again); a re-export did not show in the Overview's runs; a save racing a read of R1 was
   undone by that read's older answer. */
describe('after a mutation, what is read again', () => {
  const API = `${API_BASE_URL}/projects/p1/versions/v1`
  const wire = (key: string, text: string) => ({
    slotKind: 'description', slotKey: key, text, llmText: 'llm', humanText: text, isOverridden: true,
    isOrphaned: false, canUndo: true, updatedBy: 'u1', updatedAt: '2026-10-05T10:00:00Z',
  })
  function mount<T>(hook: () => T) {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children)
    return { client, ...renderHook(hook, { wrapper }) }
  }

  it('a discard reads the version’s review reads (R1 among them) and the rendered documents again', async () => {
    server.use(http.delete(`${API}/overrides/orphans`, () => HttpResponse.json({ discarded: 2 })))
    const { client, result } = mount(() => useDiscardOrphans('p1', 'v1'))
    const spy = vi.spyOn(client, 'invalidateQueries')
    await act(async () => { await result.current.mutateAsync() })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.review('p1', 'v1') })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.documentRenders('p1') })
  })

  it('a re-export reads R9 and the project’s runs again', async () => {
    server.use(http.post(`${API}/reexport`, () => HttpResponse.json({ job_id: 'j1', status: 'queued' }, { status: 202 })))
    const { client, result } = mount(() => useReexportVersion('p1', 'v1'))
    const spy = vi.spyOn(client, 'invalidateQueries')
    await act(async () => { await result.current.mutateAsync() })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.exportReadiness('p1', 'v1') })
    expect(spy).toHaveBeenCalledWith({ queryKey: projectKeys.runs('p1') })
  })

  it('a save stops a read of R1 begun before it: the older answer does not undo the save', async () => {
    let release = () => {}
    const held = new Promise<void>((r) => { release = r })
    let stored = 'before'
    let reads = 0
    server.use(
      http.get(`${API}/overrides`, async () => {
        reads += 1
        const text = stored                                      // the answer as the read began
        if (reads === 2) await held                              // the read under way at the save
        return HttpResponse.json({ overrides: [wire('k1', text)], total: 1, limit: 1000, offset: 0 })
      }),
      http.put(`${API}/overrides/slot`, () => { stored = 'after'; return HttpResponse.json(wire('k1', 'after')) }),
    )
    const { client, result } = mount(() => ({ list: useVersionOverrides('p1', 'v1'), save: useSaveSlot('p1', 'v1') }))
    await waitFor(() => expect(result.current.list.data?.[0]?.text).toBe('before'))
    void client.refetchQueries({ queryKey: projectKeys.overrides('p1', 'v1') })
    await waitFor(() => expect(reads).toBe(2))
    await act(async () => { await result.current.save.mutateAsync({ slot: result.current.list.data![0], text: 'after' }) })
    await waitFor(() => expect(result.current.list.data?.[0]?.text).toBe('after'))
    release()
    await new Promise((r) => setTimeout(r, 50))
    expect(client.getQueryData<Slot[]>(projectKeys.overrides('p1', 'v1'))?.[0]?.text).toBe('after')
    // The read it stopped was asked for (a discard, a job's end): R1 is read again, not left as patched.
    expect(reads).toBe(3)
  })

  it('a save with no read of R1 under way patches it, and does not read it again', async () => {
    let reads = 0
    server.use(
      http.get(`${API}/overrides`, () => {
        reads += 1
        return HttpResponse.json({ overrides: [wire('k1', 'before')], total: 1, limit: 1000, offset: 0 })
      }),
      http.put(`${API}/overrides/slot`, () => HttpResponse.json(wire('k1', 'after'))),
    )
    const { result } = mount(() => ({ list: useVersionOverrides('p1', 'v1'), save: useSaveSlot('p1', 'v1') }))
    await waitFor(() => expect(result.current.list.data?.[0]?.text).toBe('before'))
    await act(async () => { await result.current.save.mutateAsync({ slot: result.current.list.data![0], text: 'after' }) })
    await waitFor(() => expect(result.current.list.data?.[0]?.text).toBe('after'))
    await new Promise((r) => setTimeout(r, 50))
    expect(reads).toBe(1)
  })
})
