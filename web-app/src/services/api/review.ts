import { http } from '../../lib/http'
import type {
  ExportReadiness, FlowchartLabels, QueuedRegeneration, Slot, SlotHistoryEntry, SlotKind, SlotSaveResult,
} from '../../types'
import {
  mapExportReadiness, mapFlowchartLabels, mapHistory, mapRegenerationQueue, mapSlot, mapSlotSave,
  type ApiExportReadiness, type ApiFlowchartLabels, type ApiFlowchartSave, type ApiOverrides,
  type ApiRegenerationQueue, type ApiSlotSave, ApiHistorySchema,
} from '../mappers'
import type { z } from 'zod'

/* Review & update — correct the LLM's wording in a version's documents
   (docs/spec/REVIEW_UPDATE_API_SPEC.md, routes R1–R9). Every route takes the version's id, and
   a slot's key goes in the query or the body exactly as the server gave it. */

const base = (pid: string, vid: string) => `/projects/${pid}/versions/${vid}`

/** R1's largest page. */
const OVERRIDES_PAGE = 1000

/** One slot of a version: its kind and key (a key alone may name two kinds). */
export const slotId = (s: Pick<Slot, 'kind' | 'key'>): string => `${s.kind}:${s.key}`

export const reviewApi = {
  /** R1: every correction of the version, orphans included, newest first — every page of it,
   *  until `total` (a version with more than one page of corrections lost the rest). */
  overrides: async (pid: string, vid: string): Promise<Slot[]> => {
    // By kind + key: a save between two pages shifts the rows, and one comes back twice.
    const all = new Map<string, Slot>()
    for (let offset = 0; ;) {
      const r = await http.get<ApiOverrides>(`${base(pid, vid)}/overrides`,
        { limit: OVERRIDES_PAGE, offset })
      for (const s of r.overrides.map(mapSlot)) if (!all.has(slotId(s))) all.set(slotId(s), s)
      // By the page's size, not its rows: the server leaves out a row it cannot show, so a page
      // can hold fewer — and the next page starts after the whole of this one all the same.
      offset += r.limit > 0 ? r.limit : OVERRIDES_PAGE
      if (offset >= r.total) return [...all.values()]
    }
  },
  /** R12 (admins): discard orphaned corrections — every one of the version, or one slot. Final:
   *  their history goes too, and a later version made from this one does not carry them. */
  discardOrphans: async (pid: string, vid: string, slot?: Pick<Slot, 'kind' | 'key'>): Promise<number> => {
    const r = await http.del<{ discarded: number }>(`${base(pid, vid)}/overrides/orphans`,
      slot ? { slot_kind: slot.kind, slot_key: slot.key } : undefined)
    return r?.discarded ?? 0
  },
  /** R3: save one text (description, an input or output name, a unit or struct description). */
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
  /** R9: which Word files are out of date, what holds the version, and the latest update. With a
   *  document, only that document (REVIEW_APPROVE_API_SPEC A15). */
  readiness: async (pid: string, vid: string, documentId?: string): Promise<ExportReadiness> =>
    mapExportReadiness(await http.get<ApiExportReadiness>(`${base(pid, vid)}/export-readiness`,
      { document_id: documentId })),
  /** R10: the texts the next run rewrites, because a correction they were written from changed.
   *  Not paged. */
  regenerationQueue: async (pid: string, vid: string): Promise<QueuedRegeneration[]> =>
    mapRegenerationQueue(await http.get<ApiRegenerationQueue>(`${base(pid, vid)}/regeneration-queue`)),
  // Updating the Word files (POST V/reexport) is services/api/wordFiles.ts.
}
