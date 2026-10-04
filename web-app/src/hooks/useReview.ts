import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { reviewApi, slotId } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'
import { ApiError } from '../lib/http'
import type { ExportReadiness, QueuedSlot, Slot, SlotSaveResult } from '../types'

/* Review & update: correct the LLM's wording in a version's documents. A save changes the page
   (after its render is read again) but not the Word file: R9 says what a re-export still owes. */

const REEXPORT_ACTIVE = ['queued', 'running']

export function reexportActive(r: ExportReadiness | undefined): boolean {
  return !!r?.reexport && REEXPORT_ACTIVE.includes(r.reexport.status)
}

/** R9, polled while a re-export runs. */
export function useExportReadiness(projectId: string, versionId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.exportReadiness(projectId, versionId ?? ''),
    queryFn: () => reviewApi.readiness(projectId, versionId as string),
    enabled: !!projectId && !!versionId,
    refetchInterval: (q) => (reexportActive(q.state.data) ? 2500 : false),
  })
}

/** R1: the version's corrections, orphans included. */
export function useVersionOverrides(projectId: string, versionId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.overrides(projectId, versionId ?? ''),
    queryFn: () => reviewApi.overrides(projectId, versionId as string),
    enabled: !!projectId && !!versionId,
  })
}

/** R10: the version's texts the next run rewrites, read-only. */
export function useRegenerationQueue(projectId: string, versionId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.regenerationQueue(projectId, versionId ?? ''),
    queryFn: () => reviewApi.regenerationQueue(projectId, versionId as string),
    enabled: !!projectId && !!versionId,
  })
}

/** R5, read only when the history is opened. */
export function useSlotHistory(projectId: string, versionId: string, slot: Slot, enabled: boolean) {
  return useQuery({
    queryKey: projectKeys.slotHistory(projectId, versionId, slot.kind, slot.key),
    queryFn: () => reviewApi.history(projectId, versionId, slot.kind, slot.key),
    enabled: enabled && !!projectId && !!versionId,
  })
}

/** R7, read when the label editor opens. */
export function useFlowchartLabels(projectId: string, versionId: string, flowchartId: string | null) {
  return useQuery({
    queryKey: projectKeys.flowchartLabels(projectId, versionId, flowchartId ?? ''),
    queryFn: () => reviewApi.flowchartLabels(projectId, versionId, flowchartId as string),
    enabled: !!projectId && !!versionId && !!flowchartId,
    staleTime: 0,
  })
}

/** A slot as R1 lists it: a save's answer without what the save did. */
function asSlot(r: Slot): Slot {
  const s: Slot & Partial<Pick<SlotSaveResult, 'previousText' | 'firstEdit' | 'queuedForRegeneration'>> = { ...r }
  delete s.previousText
  delete s.firstEdit
  delete s.queuedForRegeneration
  return s
}

/** R1's cache with the slots a save answered with: each replaces its own row (kind + key), and
 *  goes first — R1 is newest first. A save always leaves a record (an undo too), so a slot not
 *  listed yet is added. No cache yet: left alone, the next read fetches it. */
export function patchOverrides(old: Slot[] | undefined, saved: Slot[]): Slot[] | undefined {
  if (!old) return old
  const fresh = saved.map(asSlot)
  const ids = new Set(fresh.map(slotId))
  return [...fresh, ...old.filter((s) => !ids.has(slotId(s)))]
}

/** After a save: R1 patched with the save's answer (re-reading every page of it after each save
 *  was the cost of a version with many corrections); the version's other review reads (R9, R10,
 *  a history, a flowchart's labels) and every rendered document read again (the corrected text
 *  shows on the page; a label is in the SWE.4 test steps too). */
function useAfterSave(projectId: string, versionId: string) {
  const qc = useQueryClient()
  return (saved: Slot[]) => {
    qc.setQueryData<Slot[]>(projectKeys.overrides(projectId, versionId), (old) => patchOverrides(old, saved))
    qc.invalidateQueries({
      queryKey: projectKeys.review(projectId, versionId),
      predicate: (q) => q.queryKey[4] !== 'overrides',
    })
    qc.invalidateQueries({ queryKey: projectKeys.documentRenders(projectId) })
  }
}

function quote(s: string, max = 80): string {
  const one = s.replace(/\s+/g, ' ').trim()
  return `“${one.length > max ? `${one.slice(0, max - 1)}…` : one}”`
}

/** A slot kind in words, one and many. */
const KIND_WORDS: Record<string, [string, string]> = {
  description: ['description', 'descriptions'],
  behaviourInputName: ['input name', 'input names'],
  behaviourOutputName: ['output name', 'output names'],
  behaviourDescription: ['behaviour row', 'behaviour rows'],
  unitDescription: ['unit description', 'unit descriptions'],
  structDescription: ['struct description', 'struct descriptions'],
  nodeLabel: ['flowchart label', 'flowchart labels'],
}

export function kindWords(kind: string, n = 1): string {
  const w = KIND_WORDS[kind]
  return w ? w[n === 1 ? 0 : 1] : kind
}

/** Which texts a save queued, in words: up to three by name when the answer names them (the key
 *  is never taken apart), otherwise each kind with its count. */
export function describeQueued(queued: QueuedSlot[]): string {
  const named = queued.filter((q) => q.label)
  if (named.length) {
    const shown = named.slice(0, 3).map((q) => `the ${kindWords(q.slotKind)} of ${q.label}`)
    const more = queued.length - shown.length
    return shown.join(', ') + (more ? ` and ${more} more` : '')
  }
  const byKind = new Map<string, number>()
  for (const q of queued) byKind.set(q.slotKind, (byKind.get(q.slotKind) ?? 0) + 1)
  return [...byKind].map(([k, n]) => `${n} ${kindWords(k, n)}`).join(', ')
}

/** What a save changed, in words: what it replaced, and what the next run rewrites. */
export function describeSave(r: Pick<SlotSaveResult, 'previousText' | 'queuedForRegeneration'>): string {
  const parts: string[] = []
  if (r.previousText) parts.push(`You replaced ${quote(r.previousText)}.`)
  const n = r.queuedForRegeneration.length
  if (n) {
    parts.push(`The next run rewrites ${n} text${n === 1 ? '' : 's'} that depend${n === 1 ? 's' : ''} on it: `
      + `${describeQueued(r.queuedForRegeneration)}.`)
  }
  return parts.join(' ')
}

/** The save met a run regenerating the version: nothing was saved, and saving again works only
 *  once the run has finished (API spec §8, 409 `VERSION_REGENERATING`). */
export function isRegenerating(e: unknown): boolean {
  return e instanceof ApiError && e.status === 409 && e.code === 'VERSION_REGENERATING'
}

export const REGENERATING_MESSAGE =
  'A run is regenerating this version — nothing was saved. Save again once it has finished.'

/** A save refused because a document printing the text is approved (REVIEW_APPROVE_API_SPEC
 *  "Corrections on an approved document"), or because a run is regenerating the version. Any
 *  other refusal says what the server said. */
export function saveErrorMessage(e: Error): string {
  if (e instanceof ApiError && e.status === 409) {
    if (e.code === 'DOCUMENT_APPROVED') {
      return 'A document that prints this text is approved, so it is locked. An admin can reopen it. Nothing was saved.'
    }
    if (isRegenerating(e)) return REGENERATING_MESSAGE
  }
  return e.message
}

/** Under a box whose save failed. A refusal (4xx) comes back the same if sent again, so only a
 *  fault (5xx, no answer) is invited to retry; a regenerating run, once it has finished. */
export function saveFailedNote(e: unknown): string {
  if (isRegenerating(e)) return `${REGENERATING_MESSAGE} Your text is still here.`
  if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
    const why = saveErrorMessage(e).trim()
    return `Not saved: ${why}${/[.!?]$/.test(why) ? '' : '.'} Your text is still here.`
  }
  return 'Not saved — your text is still here. Leave the box again to retry.'
}

function useSaveError(projectId: string, title: string) {
  const qc = useQueryClient()
  return (e: Error) => {
    // Approved meanwhile: read the documents again, so the page locks.
    if (e instanceof ApiError && e.code === 'DOCUMENT_APPROVED') {
      qc.invalidateQueries({ queryKey: projectKeys.documentsAll(projectId), predicate: (q) => q.queryKey[3] !== 'render' })
    }
    toast.error(title, saveErrorMessage(e))
  }
}

/** R3, or R6 for a behaviour row's bullets. */
export function useSaveSlot(projectId: string, versionId: string) {
  const after = useAfterSave(projectId, versionId)
  const onError = useSaveError(projectId, 'Not saved')
  return useMutation({
    mutationFn: ({ slot, text }: { slot: Slot; text: string }) =>
      slot.kind === 'behaviourDescription'
        ? reviewApi.saveBehaviour(projectId, versionId, slot.functionId ?? '', slot.externalCallerId ?? '',
          text.split('\n').map((l) => l.replace(/^\s*[•-]\s*/, '').trim()).filter(Boolean))
        : reviewApi.saveSlot(projectId, versionId, slot.kind, slot.key, text),
    onSuccess: (r) => { after([r]); toast.success('Saved', describeSave(r)) },
    onError,
  })
}

/** R4: back to the LLM's wording. */
export function useUndoSlot(projectId: string, versionId: string) {
  const after = useAfterSave(projectId, versionId)
  const onError = useSaveError(projectId, 'Undo failed')
  return useMutation({
    mutationFn: (slot: Slot) => reviewApi.undo(projectId, versionId, slot.kind, slot.key),
    onSuccess: (r) => { after([r]); toast.success('Back to the LLM’s text', 'The history keeps your correction.') },
    onError,
  })
}

/** R8: one flowchart's changed labels, saved together. */
export function useSaveFlowchartLabels(projectId: string, versionId: string) {
  const after = useAfterSave(projectId, versionId)
  const onError = useSaveError(projectId, 'Labels not saved')
  return useMutation({
    mutationFn: ({ flowchartId, labels }: { flowchartId: string; labels: Record<string, string> }) =>
      reviewApi.saveFlowchartLabels(projectId, versionId, flowchartId, labels),
    onSuccess: (saved) => {
      after(saved)
      const n = saved.length
      toast.success(`Saved ${n} label${n === 1 ? '' : 's'}`,
        'The picture is redrawn, and the SWE.4 test steps use the new wording.')
    },
    onError,
  })
}

/** Re-export the version's Word files (admin). R9 follows it. */
export function useReexportVersion(projectId: string, versionId: string) {
  const qc = useQueryClient()
  const refresh = () => qc.invalidateQueries({ queryKey: projectKeys.exportReadiness(projectId, versionId) })
  return useMutation({
    mutationFn: (components?: string[] | void) =>
      reviewApi.reexport(projectId, versionId, components || undefined),
    onSuccess: () => { refresh(); toast.info('Re-export started', 'The Word files are being rebuilt with the corrections.') },
    onError: (e: Error) => {
      if (e instanceof ApiError && e.status === 409 && e.code === 'REEXPORT_RUNNING') {
        refresh()
        toast.info('A re-export is already running')
      } else {
        toast.error('Re-export failed to start', e.message)
      }
    },
  })
}

/** When a re-export ends, the downloads and the pages change: read them again — the documents,
 *  and the version's review reads (R9, R10, R1: a re-export re-derives, which can drain the queue
 *  and settle undone corrections) — and say so. */
export function useReexportFinished(projectId: string, versionId: string, readiness: ExportReadiness | undefined) {
  const qc = useQueryClient()
  const prev = useRef<string | undefined>(undefined)
  const status = readiness?.reexport?.status
  const error = readiness?.reexport?.errorMessage
  useEffect(() => {
    const was = prev.current
    prev.current = status
    if (!was || !REEXPORT_ACTIVE.includes(was) || !status || REEXPORT_ACTIVE.includes(status)) return
    qc.invalidateQueries({ queryKey: ['projects', projectId, 'documents'] })
    if (versionId) qc.invalidateQueries({ queryKey: projectKeys.review(projectId, versionId) })
    if (status === 'complete') toast.success('Re-export finished', 'Download now gives the corrected Word files.')
    else toast.error('Re-export failed', error ?? undefined)
  }, [status, error, projectId, versionId, qc])
}

/** R12 (admins): discard orphaned corrections — one slot, or every one of the version. Final. */
export function useDiscardOrphans(projectId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slot?: Slot | void) => reviewApi.discardOrphans(projectId, versionId, slot || undefined),
    onSuccess: (n) => {
      qc.invalidateQueries({ queryKey: projectKeys.overrides(projectId, versionId) })
      toast.success(`Discarded ${n} orphaned correction${n === 1 ? '' : 's'}`)
    },
    onError: (e: Error) => toast.error('Not discarded', e.message),
  })
}
