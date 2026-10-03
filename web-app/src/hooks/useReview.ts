import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { reviewApi } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'
import { ApiError } from '../lib/http'
import type { ExportReadiness, Slot, SlotSaveResult } from '../types'

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

/** After a save: the version's review reads, and every rendered document (the corrected text
 *  shows on the page; a label is in the SWE.4 test steps too). */
function useAfterSave(projectId: string, versionId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: projectKeys.review(projectId, versionId) })
    qc.invalidateQueries({ queryKey: projectKeys.documentRenders(projectId) })
  }
}

function quote(s: string, max = 80): string {
  const one = s.replace(/\s+/g, ' ').trim()
  return `“${one.length > max ? `${one.slice(0, max - 1)}…` : one}”`
}

/** What a save changed, in words: what it replaced, and what the next run rewrites. */
export function describeSave(r: Pick<SlotSaveResult, 'previousText' | 'queuedForRegeneration'>): string {
  const parts: string[] = []
  if (r.previousText) parts.push(`You replaced ${quote(r.previousText)}.`)
  const n = r.queuedForRegeneration.length
  if (n) parts.push(`The next run rewrites ${n} text${n === 1 ? '' : 's'} that depend${n === 1 ? 's' : ''} on it.`)
  return parts.join(' ')
}

/** A save refused because a document printing the text is approved (REVIEW_APPROVE_API_SPEC
 *  "Corrections on an approved document"), or because a run changed it under the reviewer. */
export function saveErrorMessage(e: Error): string {
  if (e instanceof ApiError && e.status === 409) {
    if (e.code === 'DOCUMENT_APPROVED') {
      return 'A document that prints this text is approved, so it is locked. An admin can reopen it. Nothing was saved.'
    }
    return 'A run changed this document while you were editing. Nothing was saved; try again.'
  }
  return e.message
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
    onSuccess: (r) => { after(); toast.success('Saved', describeSave(r)) },
    onError,
  })
}

/** R4: back to the LLM's wording. */
export function useUndoSlot(projectId: string, versionId: string) {
  const after = useAfterSave(projectId, versionId)
  const onError = useSaveError(projectId, 'Undo failed')
  return useMutation({
    mutationFn: (slot: Slot) => reviewApi.undo(projectId, versionId, slot.kind, slot.key),
    onSuccess: () => { after(); toast.success('Back to the LLM’s text', 'The history keeps your correction.') },
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
      after()
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
    mutationFn: () => reviewApi.reexport(projectId, versionId),
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

/** When a re-export ends, the downloads and the pages change: read them again, and say so. */
export function useReexportFinished(projectId: string, readiness: ExportReadiness | undefined) {
  const qc = useQueryClient()
  const prev = useRef<string | undefined>(undefined)
  const status = readiness?.reexport?.status
  const error = readiness?.reexport?.errorMessage
  useEffect(() => {
    const was = prev.current
    prev.current = status
    if (!was || !REEXPORT_ACTIVE.includes(was) || !status || REEXPORT_ACTIVE.includes(status)) return
    qc.invalidateQueries({ queryKey: ['projects', projectId, 'documents'] })
    if (status === 'complete') toast.success('Re-export finished', 'Download now gives the corrected Word files.')
    else toast.error('Re-export failed', error ?? undefined)
  }, [status, error, projectId, qc])
}
