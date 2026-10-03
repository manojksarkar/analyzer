import { http } from '../../lib/http'
import type {
  ExportReadiness, FlowchartLabels, Slot, SlotHistoryEntry, SlotKind, SlotSaveResult,
} from '../../types'
import {
  mapExportReadiness, mapFlowchartLabels, mapHistory, mapSlot, mapSlotSave,
  type ApiExportReadiness, type ApiFlowchartLabels, type ApiFlowchartSave, type ApiSlot,
  type ApiSlotSave, ApiHistorySchema,
} from '../mappers'
import type { z } from 'zod'

/* Review & update — correct the LLM's wording in a version's documents
   (docs/spec/REVIEW_UPDATE_API_SPEC.md, routes R1–R9). Every route takes the version's id, and
   a slot's key goes in the query or the body exactly as the server gave it. */

const base = (pid: string, vid: string) => `/projects/${pid}/versions/${vid}`

export const reviewApi = {
  /** R1: every correction of the version, orphans included, newest first. */
  overrides: async (pid: string, vid: string): Promise<Slot[]> => {
    const r = await http.get<{ overrides: ApiSlot[] }>(`${base(pid, vid)}/overrides`, { limit: 1000 })
    return r.overrides.map(mapSlot)
  },
  /** R3: save one text (description, a behaviour name, a unit or struct description). */
  saveSlot: async (pid: string, vid: string, kind: SlotKind, key: string, text: string): Promise<SlotSaveResult> =>
    mapSlotSave(await http.put<ApiSlotSave>(`${base(pid, vid)}/overrides/slot`,
      { slot_kind: kind, slot_key: key, text })),
  /** R6: save a Dynamic Behaviour row's bullets, all of them. */
  saveBehaviour: async (pid: string, vid: string, functionId: string, callerId: string,
    bullets: string[]): Promise<SlotSaveResult> =>
    mapSlotSave(await http.put<ApiSlotSave>(`${base(pid, vid)}/overrides/behaviour`,
      { function_id: functionId, external_caller_id: callerId, bullets })),
  /** R4: undo — back to the LLM's wording. */
  undo: async (pid: string, vid: string, kind: SlotKind, key: string): Promise<SlotSaveResult> =>
    mapSlotSave(await http.del<ApiSlotSave>(`${base(pid, vid)}/overrides/slot`,
      { slot_kind: kind, slot_key: key })),
  /** R5: one slot's saved corrections, oldest first. */
  history: async (pid: string, vid: string, kind: SlotKind, key: string): Promise<SlotHistoryEntry[]> =>
    mapHistory(await http.get<z.infer<typeof ApiHistorySchema>>(`${base(pid, vid)}/overrides/history`,
      { slot_kind: kind, slot_key: key })),
  /** R7: one flowchart's node labels. */
  flowchartLabels: async (pid: string, vid: string, flowchartId: string): Promise<FlowchartLabels> =>
    mapFlowchartLabels(await http.get<ApiFlowchartLabels>(`${base(pid, vid)}/flowcharts/labels`,
      { flowchart_id: flowchartId })),
  /** R8: save the changed labels of one flowchart together (all or nothing). */
  saveFlowchartLabels: async (pid: string, vid: string, flowchartId: string,
    labels: Record<string, string>): Promise<SlotSaveResult[]> => {
    const r = await http.put<ApiFlowchartSave>(`${base(pid, vid)}/flowcharts/labels`,
      { flowchart_id: flowchartId, labels })
    return r.labels.map(mapSlotSave)
  },
  /** R9: do the Word files have every correction? And the latest re-export. With a document,
   *  only that document's component and type (REVIEW_APPROVE_API_SPEC A15). */
  readiness: async (pid: string, vid: string, documentId?: string): Promise<ExportReadiness> =>
    mapExportReadiness(await http.get<ApiExportReadiness>(`${base(pid, vid)}/export-readiness`,
      { document_id: documentId })),
  /** Re-export the version's Word files (admin). Follow it through R9's `reexport`. */
  reexport: async (pid: string, vid: string): Promise<{ jobId: string }> => {
    const r = await http.post<{ job_id: string }>(`${base(pid, vid)}/reexport`)
    return { jobId: r.job_id }
  },
}
