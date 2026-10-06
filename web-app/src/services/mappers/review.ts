import { z } from 'zod'
import type {
  ExportReadiness, FlowchartLabels, QueuedRegeneration, QueuedSlot, Slot, SlotHistoryEntry, SlotKind,
  SlotSaveResult,
} from '../../types'
import {
  ApiReexportExtrasSchema, ApiWordFileReadinessSchema, mapReexportExtras, mapWordFileReadiness,
} from './wordFiles'

/* Review & update (docs/spec/REVIEW_UPDATE_API_SPEC.md). Unlike the rest of the API these
   routes answer in camelCase, and every one returns a slot in ONE shape (§5 `Slot`) — which the
   document render also carries beside each correctable text. */

export const ApiSlotSchema = z.object({
  slotKind: z.string(),
  slotKey: z.string(),
  text: z.string(),
  llmText: z.string().nullable(),
  humanText: z.string().nullable(),
  isOverridden: z.boolean(),
  isOrphaned: z.boolean(),
  canUndo: z.boolean(),
  updatedBy: z.string().nullable(),
  updatedAt: z.string().nullable(),
  bullets: z.array(z.string()).optional(),
  functionId: z.string().optional(),
  externalCallerId: z.string().optional(),
  flowchartId: z.string().optional(),
  nodeId: z.string().optional(),
})
export type ApiSlot = z.infer<typeof ApiSlotSchema>

/** §5 `QueuedSlot`. A readable `label` is not in the contract today; kept when a server sends one. */
export const ApiQueuedSlotSchema = z.object({
  slotKind: z.string(), slotKey: z.string(), label: z.string().nullable().optional(),
})
export type ApiQueuedSlot = z.infer<typeof ApiQueuedSlotSchema>

export const ApiSlotSaveSchema = ApiSlotSchema.extend({
  previousText: z.string().nullable().optional(),
  firstEdit: z.boolean().optional(),
  queuedForRegeneration: z.array(ApiQueuedSlotSchema).optional(),
})
export type ApiSlotSave = z.infer<typeof ApiSlotSaveSchema>

export const ApiOverridesSchema = z.object({
  overrides: z.array(ApiSlotSchema), total: z.number(), limit: z.number(), offset: z.number(),
})
export type ApiOverrides = z.infer<typeof ApiOverridesSchema>

/** R10: the regeneration queue. */
export const ApiRegenerationQueueSchema = z.object({
  pending: z.array(ApiQueuedSlotSchema.extend({
    reason: z.string().nullable().optional(),
    causedBy: ApiQueuedSlotSchema.nullable().optional(),
    requestedAt: z.string().nullable().optional(),
  })),
  total: z.number(),
})
export type ApiRegenerationQueue = z.infer<typeof ApiRegenerationQueueSchema>

export const ApiHistorySchema = z.object({
  history: z.array(z.object({
    seq: z.number(), humanText: z.string(),
    updatedBy: z.string().nullable(), updatedAt: z.string().nullable(),
  })),
})

export const ApiFlowchartLabelsSchema = z.object({
  flowchartId: z.string(),
  functionName: z.string().nullable().optional(),
  labels: z.array(ApiSlotSchema),
  graphAvailable: z.boolean(),
  note: z.string().nullable().optional(),
  dot: z.string().optional(),
})
export type ApiFlowchartLabels = z.infer<typeof ApiFlowchartLabelsSchema>

export const ApiFlowchartSaveSchema = z.object({
  flowchartId: z.string(),
  labels: z.array(ApiSlotSaveSchema),
})
export type ApiFlowchartSave = z.infer<typeof ApiFlowchartSaveSchema>

export const ApiExportReadinessSchema = z.object({
  stale: z.boolean(),
  /** The components whose Word files are behind (version-wide question); absent from an older API. */
  staleComponents: z.array(z.string()).optional(),
  reason: z.string().nullable().optional(),
  explanation: z.string().nullable().optional(),
  overrideCount: z.number(),
  pendingRenders: z.number(),
  failedRenders: z.number(),
  /** When the version's oldest derived output was written: the Word files are no older. */
  oldestDerivationAt: z.string().nullable().optional(),
  // Word file updates (mappers/wordFiles.ts): optional, as an older API sends none of them.
  ...ApiWordFileReadinessSchema.omit({ reexport: true }).shape,
  reexport: z.object({
    jobId: z.string(), status: z.string(),
    startedAt: z.string().nullable().optional(), completedAt: z.string().nullable().optional(),
    errorMessage: z.string().nullable().optional(),
    ...ApiReexportExtrasSchema.shape,
  }).nullable(),
})
export type ApiExportReadiness = z.infer<typeof ApiExportReadinessSchema>

export function mapSlot(s: ApiSlot): Slot {
  return {
    kind: s.slotKind as SlotKind,
    key: s.slotKey,
    text: s.text ?? '',
    llmText: s.llmText ?? null,
    humanText: s.humanText ?? null,
    isOverridden: !!s.isOverridden,
    isOrphaned: !!s.isOrphaned,
    canUndo: !!s.canUndo,
    updatedBy: s.updatedBy ?? null,
    updatedAt: s.updatedAt ?? null,
    ...(s.bullets ? { bullets: s.bullets } : {}),
    ...(s.functionId ? { functionId: s.functionId } : {}),
    ...(s.externalCallerId ? { externalCallerId: s.externalCallerId } : {}),
    ...(s.flowchartId ? { flowchartId: s.flowchartId } : {}),
    ...(s.nodeId ? { nodeId: s.nodeId } : {}),
  }
}

/** A slot the render may or may not carry (an older API sends none). */
export function mapSlotOrNull(s: ApiSlot | null | undefined): Slot | null {
  return s ? mapSlot(s) : null
}

function mapQueuedSlot(q: ApiQueuedSlot): QueuedSlot {
  return { slotKind: q.slotKind, slotKey: q.slotKey, ...(q.label ? { label: q.label } : {}) }
}

export function mapSlotSave(s: ApiSlotSave): SlotSaveResult {
  return {
    ...mapSlot(s),
    previousText: s.previousText ?? null,
    firstEdit: !!s.firstEdit,
    queuedForRegeneration: (s.queuedForRegeneration ?? []).map(mapQueuedSlot),
  }
}

export function mapRegenerationQueue(r: ApiRegenerationQueue): QueuedRegeneration[] {
  return r.pending.map((p) => ({
    ...mapQueuedSlot(p),
    reason: p.reason ?? '',
    causedBy: p.causedBy ? mapQueuedSlot(p.causedBy) : null,
    requestedAt: p.requestedAt ?? null,
  }))
}

export function mapHistory(h: z.infer<typeof ApiHistorySchema>): SlotHistoryEntry[] {
  return h.history.map((e) => ({
    seq: e.seq, humanText: e.humanText, updatedBy: e.updatedBy ?? null, updatedAt: e.updatedAt ?? null,
  }))
}

export function mapFlowchartLabels(r: ApiFlowchartLabels): FlowchartLabels {
  return {
    flowchartId: r.flowchartId,
    functionName: r.functionName ?? '',
    labels: r.labels.map(mapSlot),
    graphAvailable: r.graphAvailable,
    note: r.note ?? null,
    dot: r.dot ?? '',
  }
}

export function mapExportReadiness(r: ApiExportReadiness): ExportReadiness {
  return {
    stale: r.stale,
    ...(r.staleComponents ? { staleComponents: r.staleComponents } : {}),
    explanation: r.explanation ?? null,
    overrideCount: r.overrideCount,
    pendingRenders: r.pendingRenders,
    failedRenders: r.failedRenders,
    oldestDerivationAt: r.oldestDerivationAt ?? null,
    // Word file updates: which files are out of date, what holds the version (mappers/wordFiles.ts).
    ...mapWordFileReadiness(r),
    reexport: r.reexport ? {
      jobId: r.reexport.jobId,
      status: r.reexport.status,
      startedAt: r.reexport.startedAt ?? null,
      completedAt: r.reexport.completedAt ?? null,
      errorMessage: r.reexport.errorMessage ?? null,
      ...mapReexportExtras(r.reexport),
    } : null,
  }
}
