import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { reviewApi, slotId } from '../services/api'
import { projectKeys } from './useProjects'
import { readinessPollMs } from '../lib/wordFiles'
import { toast } from '../components/ui/Toast'
import { ApiError } from '../lib/http'
import type { QueuedSlot, Slot, SlotSaveResult } from '../types'

/* Review & update: correct the LLM's wording in a version's documents. A save changes the page
   (after its render is read again) but not the Word file: R9 says which Word files are out of
   date until they are updated. */

/** R9, polled while an update writes Word files (and slowly while a run holds the version). */
export function useExportReadiness(projectId: string, versionId: string | undefined) {
  return useQuery({
    queryKey: projectKeys.exportReadiness(projectId, versionId ?? ''),
    queryFn: () => reviewApi.readiness(projectId, versionId as string),
    enabled: !!projectId && !!versionId,
    refetchInterval: (q) => readinessPollMs(q.state.data),
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
  return async (saved: Slot[]) => {
    // A read of R1 under way began before this save: its answer would put the saved slots back
    // as they were. Stop it, then patch what is cached — or, with nothing cached yet, read again.
    // A read that was stopped was asked for by something (a discard, a job's end, a focus): its
    // ask must not be lost with it, so R1 is read again — the save is in that answer.
    const key = projectKeys.overrides(projectId, versionId)
    const stopped = qc.isFetching({ queryKey: key, exact: true }) > 0
    await qc.cancelQueries({ queryKey: key, exact: true })
    if (qc.getQueryData(key)) {
      qc.setQueryData<Slot[]>(key, (old) => patchOverrides(old, saved))
      if (stopped) qc.invalidateQueries({ queryKey: key, exact: true })
    } else qc.invalidateQueries({ queryKey: key, exact: true })
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
  inputName: ['input name', 'input names'],
  outputName: ['output name', 'output names'],
  behaviourDescription: ['behaviour row', 'behaviour rows'],
  unitDescription: ['unit description', 'unit descriptions'],
  structDescription: ['struct description', 'struct descriptions'],
  nodeLabel: ['flowchart label', 'flowchart labels'],
  // Queued only, never edited: a chart's node labels, which the LLM writes together (R10).
  flowchartLabels: ['flowchart labels', 'flowcharts’ labels'],
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

/** The save met an update writing its component's Word file: nothing was saved, and corrections
 *  there wait until it ends (409 `WORD_FILE_UPDATING`; WORD_FILE_UPDATES D5). Every other
 *  component stays editable. */
export function isWordFileUpdating(e: unknown): boolean {
  return e instanceof ApiError && e.status === 409 && e.code === 'WORD_FILE_UPDATING'
}

export const WORD_FILE_UPDATING_MESSAGE = 'Corrections wait until the update is done.'

/** A save refused because a document printing the text is approved (REVIEW_APPROVE_API_SPEC
 *  "Corrections on an approved document"), because a run is regenerating the version, or because
 *  an update writes its component's Word file. Any other refusal says what the server said. */
export function saveErrorMessage(e: Error): string {
  if (e instanceof ApiError && e.status === 409) {
    if (e.code === 'DOCUMENT_APPROVED') {
      return 'A document that prints this text is approved, so it is locked. An admin can reopen it. Nothing was saved.'
    }
    if (isRegenerating(e)) return REGENERATING_MESSAGE
    if (isWordFileUpdating(e)) return WORD_FILE_UPDATING_MESSAGE
  }
  return e.message
}

/** Under a box whose save failed. A refusal (4xx) comes back the same if sent again, so only a
 *  fault (5xx, no answer) is invited to retry; a regenerating run, once it has finished; an
 *  update, once it is done. */
export function saveFailedNote(e: unknown): string {
  if (isRegenerating(e)) return `${REGENERATING_MESSAGE} Your text is still here.`
  if (isWordFileUpdating(e)) return `${WORD_FILE_UPDATING_MESSAGE} Your text is still here.`
  if (e instanceof ApiError && e.status >= 400 && e.status < 500) {
    const why = saveErrorMessage(e).trim()
    return `Not saved: ${why}${/[.!?]$/.test(why) ? '' : '.'} Your text is still here.`
  }
  return 'Not saved — your text is still here. Leave the box again to retry.'
}

function useSaveError(projectId: string, versionId: string, title: string) {
  const qc = useQueryClient()
  return (e: Error) => {
    // Approved meanwhile: read the documents again, so the page locks.
    if (e instanceof ApiError && e.code === 'DOCUMENT_APPROVED') {
      qc.invalidateQueries({ queryKey: projectKeys.documentsAll(projectId), predicate: (q) => q.queryKey[3] !== 'render' })
    }
    // An update started meanwhile: read R9 again, so the edit bar holds and says why.
    if (isWordFileUpdating(e)) qc.invalidateQueries({ queryKey: projectKeys.exportReadiness(projectId, versionId) })
    toast.error(title, saveErrorMessage(e))
  }
}

/** Every correction save of a version (R3, R4, R6, R8): `useIsMutating` with it says whether one
 *  is still under way. Each stays pending until the reads it changes (R9 among them) are asked
 *  again, so "no save pending, R9 not fetching" means R9 has every save. */
export const correctionSaveKey = (projectId: string, versionId: string) =>
  ['review', 'save', projectId, versionId] as const

/** R3, or R6 for a behaviour row's bullets. */
export function useSaveSlot(projectId: string, versionId: string) {
  const after = useAfterSave(projectId, versionId)
  const onError = useSaveError(projectId, versionId, 'Not saved')
  return useMutation({
    mutationKey: correctionSaveKey(projectId, versionId),
    mutationFn: ({ slot, text }: { slot: Slot; text: string }) =>
      slot.kind === 'behaviourDescription'
        ? reviewApi.saveBehaviour(projectId, versionId, slot.functionId ?? '', slot.externalCallerId ?? '',
          text.split('\n').map((l) => l.replace(/^\s*[•-]\s*/, '').trim()).filter(Boolean))
        : reviewApi.saveSlot(projectId, versionId, slot.kind, slot.key, text),
    // Pending until R9 and the others are read again (Done editing waits for that).
    onSuccess: async (r) => { toast.success('Saved', describeSave(r)); await after([r]) },
    onError,
  })
}

/** R4: back to the LLM's wording. */
export function useUndoSlot(projectId: string, versionId: string) {
  const after = useAfterSave(projectId, versionId)
  const onError = useSaveError(projectId, versionId, 'Undo failed')
  return useMutation({
    mutationKey: correctionSaveKey(projectId, versionId),
    mutationFn: (slot: Slot) => reviewApi.undo(projectId, versionId, slot.kind, slot.key),
    onSuccess: async (r) => {
      toast.success('Back to the LLM’s text', 'The history keeps your correction.')
      await after([r])
    },
    onError,
  })
}

/** R8: one flowchart's changed labels, saved together. */
export function useSaveFlowchartLabels(projectId: string, versionId: string) {
  const after = useAfterSave(projectId, versionId)
  const onError = useSaveError(projectId, versionId, 'Labels not saved')
  return useMutation({
    mutationKey: correctionSaveKey(projectId, versionId),
    mutationFn: ({ flowchartId, labels }: { flowchartId: string; labels: Record<string, string> }) =>
      reviewApi.saveFlowchartLabels(projectId, versionId, flowchartId, labels),
    onSuccess: async (saved) => {
      const n = saved.length
      toast.success(`Saved ${n} label${n === 1 ? '' : 's'}`,
        'The picture is redrawn, and the SWE.4 test steps use the new wording.')
      await after(saved)
    },
    onError,
  })
}

/* Updating the Word files — starting one, following it, saying when it ends — is
   hooks/useWordFiles.ts (WORD_FILE_UPDATES). */

/** R12 (admins): discard orphaned corrections — one slot, or every one of the version. Final. */
export function useDiscardOrphans(projectId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (slot?: Slot | void) => reviewApi.discardOrphans(projectId, versionId, slot || undefined),
    onSuccess: (n) => {
      // R1 and the version's other review reads (under `review`), and the rendered documents:
      // an edit box's slot comes from the render, and kept its orphan note until a reload.
      qc.invalidateQueries({ queryKey: projectKeys.review(projectId, versionId) })
      qc.invalidateQueries({ queryKey: projectKeys.documentRenders(projectId) })
      toast.success(`Discarded ${n} orphaned correction${n === 1 ? '' : 's'}`)
    },
    onError: (e: Error) => toast.error('Not discarded', e.message),
  })
}
