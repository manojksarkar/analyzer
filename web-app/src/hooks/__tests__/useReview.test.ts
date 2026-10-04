import { createElement, type ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { renderHook } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError } from '../../lib/http'
import type { ExportReadiness, Slot, SlotSaveResult } from '../../types'
import { projectKeys } from '../useProjects'
import {
  describeQueued, describeSave, isRegenerating, patchOverrides, saveErrorMessage, saveFailedNote,
  useReexportFinished,
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
