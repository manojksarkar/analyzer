import { z } from 'zod'
import type {
  Document, DocStats, DocumentDetail,
  RichDocument, RichSection, RichSectionType, TocEntry, DocCover, DocMeta,
  FlowchartEntry, FlowchartTableData, BehaviorTableData, TestSpecData, TestSummary,
} from '../../types'
import { formatShortDate, avatarPalette } from '../../lib/format'
import { reviewStatusOf } from '../../lib/reviewStatus'
import { API_BASE_URL } from '../../lib/http'
import { ApiSlotSchema, mapSlotOrNull, type ApiSlot } from './review'
import { ApiDocReviewSchema, ApiUserRefSchema, mapDocReview, mapUserRef } from './approval'

/** @deprecated the same person as `reviewer`, as a list of 0 or 1 (kept for older clients). */
export const ApiAssigneeSchema = ApiUserRefSchema
export type ApiAssignee = z.infer<typeof ApiAssigneeSchema>

// A document, from every route that returns one (REVIEW_APPROVE_API_SPEC §2): its one reviewer
// (null = "Needs a reviewer") and its review. `due_date` is still sent; nothing shows it.
export const ApiDocumentSchema = z.object({
  id: z.string(), name: z.string(), subtitle: z.string(), process: z.string(),
  layer: z.string(), group: z.string(), status: z.string(), version_id: z.string(),
  due_date: z.string().nullable(), assignees: z.array(ApiAssigneeSchema),
  reviewer: ApiUserRefSchema.nullable(),
  review: ApiDocReviewSchema,
  created_at: z.string(), updated_at: z.string(),
})
export type ApiDocument = z.infer<typeof ApiDocumentSchema>

// `GET …/documents/{id}`: the same document. The placeholder sections it may still carry are
// not read (review is per document, not per section).
export const ApiDocumentDetailSchema = ApiDocumentSchema
export type ApiDocumentDetail = ApiDocument

/**
 * @param versionTagById optional version_id → tag lookup so the UI can show
 * "v1.2.0" instead of the raw "ver3" id when the caller has versions cached.
 */
export function mapDocument(d: ApiDocument, versionTagById?: Record<string, string>): Document {
  // An API from before review and approval sends `assignees` only.
  const reviewer = mapUserRef(d.reviewer !== undefined ? d.reviewer : d.assignees?.[0])
  const pal = reviewer ? avatarPalette(reviewer.userId) : undefined
  return {
    id: d.id,
    name: d.name,
    process: d.process,
    status: reviewStatusOf(d.status),
    version: versionTagById?.[d.version_id] ?? d.version_id,
    versionId: d.version_id,
    updatedAt: formatShortDate(d.updated_at) ?? '',
    subtitle: d.subtitle || undefined,
    layer: d.layer || undefined,
    group: d.group || undefined,
    reviewer,
    review: mapDocReview(d.review),
    assignee: reviewer?.name,
    assigneeInitials: reviewer?.initials,
    assigneeColor: pal?.bg,
    assigneeTextColor: pal?.text,
  }
}

/** GET …/documents/{id}: one document, as a list row. */
export function mapDocumentDetail(
  d: ApiDocumentDetail,
  versionTagById?: Record<string, string>,
): DocumentDetail {
  return mapDocument(d, versionTagById)
}

/* ── Rich render payload ── */

// One flowchart's SVG, or why there is none. The DOT is not sent (a document can hold 500+).
// `status` is a plain string so an unknown one degrades to "missing" rather than failing the
// whole document's parse; an API from before SVGs sends none of these but `image_url`.
const ApiFlowchartSchema = z.object({
  label: z.string(),
  status: z.string().optional(),
  image_url: z.string().nullable().optional(),
  width: z.number().nullable().optional(),
  height: z.number().nullable().optional(),
  boxes: z.number().optional(),
  source_hash: z.string().nullable().optional(),
  // Review & update: the chart's id for the label editor, and whether it has labels to edit.
  flowchart_id: z.string().nullable().optional(),
  editable: z.boolean().optional(),
})
type ApiFlowchart = z.infer<typeof ApiFlowchartSchema>

// A correctable text's slot (review & update); an older API sends none.
const ApiSlotRefSchema = ApiSlotSchema.nullable().optional()

const ApiFlowchartTableSchema = z.object({
  description: z.string(),
  flowcharts: z.array(ApiFlowchartSchema),
  risk: z.string(),
  capacity: z.string(),
  input_name: z.string(),
  output_name: z.string(),
  description_slot: ApiSlotRefSchema,
  input_name_slot: ApiSlotRefSchema,
  output_name_slot: ApiSlotRefSchema,
})
type ApiFlowchartTable = z.infer<typeof ApiFlowchartTableSchema>

const ApiBehaviorTableSchema = z.object({
  description_list: z.array(z.string()),
  risk: z.string(),
  capacity: z.string(),
  input_name: z.string(),
  output_name: z.string(),
  diagram_url: z.string().nullable().optional(),
  description_slot: ApiSlotRefSchema,
  input_name_slot: ApiSlotRefSchema,
  output_name_slot: ApiSlotRefSchema,
})
type ApiBehaviorTable = z.infer<typeof ApiBehaviorTableSchema>

const ApiTestSpecSchema = z.object({
  test_case_id: z.string(),
  generation_method: z.string(),
  return_type: z.string(),
  equipment: z.string(),
  platform: z.string(),
  priority: z.string(),
  environment: z.string(),
  precondition: z.object({
    mocks: z.array(z.string()), parameters: z.array(z.string()), globals: z.array(z.string()),
  }),
  inputs: z.array(z.string()),
  steps: z.array(z.object({ number: z.string(), text: z.string() })),
  expected: z.array(z.object({ text: z.string(), steps: z.array(z.string()) })),
  expected_note: z.string().nullable(),
})
type ApiTestSpec = z.infer<typeof ApiTestSpecSchema>

const ApiTestSummarySchema = z.object({
  units: z.number(), function_specs: z.number(), dynamic_specs: z.number(), mocks: z.number(),
  equipment: z.string(), platform: z.string(),
})

// Recursive section — the type is hand-declared and the schema is built with
// `z.lazy` so it can reference itself (zod can't infer a self-referential type).
interface ApiRichSection {
  id: string; number: string; title: string; level: number; type: string
  content: string | null
  table: { headers: string[]; rows: string[][]; cell_slots?: (ApiSlot | null)[][] | null } | null
  image_url?: string | null; mermaid?: string | null
  children: ApiRichSection[]
  flowchart_table?: ApiFlowchartTable | null
  behavior_table?: ApiBehaviorTable | null
  test_spec?: ApiTestSpec | null
  content_slot?: ApiSlot | null
}
const ApiRichSectionSchema: z.ZodType<ApiRichSection> = z.lazy(() =>
  z.object({
    id: z.string(), number: z.string(), title: z.string(), level: z.number(), type: z.string(),
    content: z.string().nullable(),
    table: z.object({
      headers: z.array(z.string()), rows: z.array(z.array(z.string())),
      cell_slots: z.array(z.array(ApiSlotSchema.nullable())).nullable().optional(),
    }).nullable(),
    image_url: z.string().nullable().optional(),
    mermaid: z.string().nullable().optional(),
    children: z.array(ApiRichSectionSchema),
    flowchart_table: ApiFlowchartTableSchema.nullable().optional(),
    behavior_table: ApiBehaviorTableSchema.nullable().optional(),
    test_spec: ApiTestSpecSchema.nullable().optional(),
    content_slot: ApiSlotSchema.nullable().optional(),
  }),
)

export const ApiRichDocumentSchema = z.object({
  cover: z.object({
    project_name: z.string(), subtitle: z.string(), version: z.string(),
    layer: z.string(), group: z.string(),
    standard: z.string().optional(), process: z.string().optional(), generated_at: z.string().optional(),
  }),
  toc: z.array(z.object({
    id: z.string(), number: z.string(), title: z.string(), level: z.number(),
  })),
  sections: z.array(ApiRichSectionSchema),
  meta: z.object({
    pipeline_data_available: z.boolean(), model_data_available: z.boolean(),
    source: z.string(), layers: z.array(z.string()), components: z.array(z.string()),
    units_total: z.number(), functions_total: z.number(), globals_total: z.number(),
  }),
  test_summary: ApiTestSummarySchema.nullable().optional(),
})
export type ApiRichDocument = z.infer<typeof ApiRichDocumentSchema>

function mapTestSpec(t: ApiTestSpec): TestSpecData {
  return {
    testCaseId: t.test_case_id,
    generationMethod: t.generation_method,
    returnType: t.return_type,
    equipment: t.equipment,
    platform: t.platform,
    priority: t.priority,
    environment: t.environment,
    precondition: t.precondition,
    inputs: t.inputs,
    steps: t.steps,
    expected: t.expected,
    expectedNote: t.expected_note,
  }
}

export function mapFlowchart(fc: ApiFlowchart): FlowchartEntry {
  const imageUrl = withVersion(resolveAssetUrl(fc.image_url), fc.source_hash)
  return {
    label: fc.label ?? '',
    status: fc.status === 'too_large' ? 'too_large' : imageUrl ? 'drawn' : 'missing',
    imageUrl: fc.status === 'too_large' ? null : imageUrl,
    width: fc.width ?? null,
    height: fc.height ?? null,
    boxes: fc.boxes ?? 0,
    flowchartId: fc.flowchart_id ?? null,
    editable: !!(fc.flowchart_id && fc.editable),
  }
}

/** The SVG's URL changes with its drawing: a corrected label is redrawn under the same file
 *  name, and an `<img>` keeps the picture it has for an unchanged `src`. Added after
 *  `resolveAssetUrl` so it stays a query parameter of its own in either asset-URL shape. */
function withVersion(url: string | null, sourceHash: string | null | undefined): string | null {
  if (!url || !sourceHash) return url
  return `${url}${url.includes('?') ? '&' : '?'}v=${encodeURIComponent(sourceHash)}`
}

function mapRichSection(s: ApiRichSection): RichSection {
  let flowchartTable: FlowchartTableData | null = null
  if (s.flowchart_table) {
    const ft = s.flowchart_table
    flowchartTable = {
      description: ft.description,
      flowcharts: (ft.flowcharts ?? []).map(mapFlowchart),
      risk: ft.risk,
      capacity: ft.capacity,
      inputName: ft.input_name,
      outputName: ft.output_name,
      descriptionSlot: mapSlotOrNull(ft.description_slot),
      inputNameSlot: mapSlotOrNull(ft.input_name_slot),
      outputNameSlot: mapSlotOrNull(ft.output_name_slot),
    }
  }

  let behaviorTable: BehaviorTableData | null = null
  if (s.behavior_table) {
    const bt = s.behavior_table
    behaviorTable = {
      descriptionList: bt.description_list ?? [],
      risk: bt.risk,
      capacity: bt.capacity,
      inputName: bt.input_name,
      outputName: bt.output_name,
      diagramUrl: resolveAssetUrl(bt.diagram_url),
      descriptionSlot: mapSlotOrNull(bt.description_slot),
      inputNameSlot: mapSlotOrNull(bt.input_name_slot),
      outputNameSlot: mapSlotOrNull(bt.output_name_slot),
    }
  }

  return {
    id: s.id,
    number: s.number,
    title: s.title,
    level: s.level,
    type: (s.type as RichSectionType) ?? 'richtext',
    content: s.content,
    table: s.table ? {
      headers: s.table.headers,
      rows: s.table.rows,
      ...(s.table.cell_slots
        ? { cellSlots: s.table.cell_slots.map((row) => row.map((c) => mapSlotOrNull(c))) }
        : {}),
    } : null,
    imageUrl: resolveAssetUrl(s.image_url),
    mermaid: s.mermaid ?? null,
    children: (s.children ?? []).map(mapRichSection),
    flowchartTable,
    behaviorTable,
    testSpec: s.test_spec ? mapTestSpec(s.test_spec) : null,
    contentSlot: mapSlotOrNull(s.content_slot),
  }
}

/**
 * Resolve a diagram asset reference (from the render payload) to a URL an `<img>`
 * can lazy-load. The API returns a relative **path/key**, not a ready link — the
 * UI builds the URL. Two shapes, selected by `VITE_ASSET_ENDPOINT`:
 *
 *  - **unset (default)** — the ref is a path under the API base:
 *      `${API_BASE_URL}/<ref>`              (matches the mock's REST asset route)
 *  - **set** (e.g. `/assets`) — hand the path to a dedicated asset endpoint as a
 *    query param (the real-API model):
 *      `${API_BASE_URL}/assets?path=<ref>`
 *
 * An absolute / protocol-relative ref always passes through unchanged (a backend
 * that returns a full CDN/pre-signed link needs no config). This is the ONE place
 * the asset-URL contract lives — change here when the real endpoint is fixed.
 *
 * Caveat: an `<img>` sends no `Authorization` header, so whichever endpoint serves
 * the bytes must be reachable without a Bearer (the `path` query carries the asset
 * path, never a token). If assets MUST be authenticated, the inspector switches to
 * a blob fetch (auth GET → objectURL) instead — see INTEGRATION_NOTES.
 */
const ASSET_ENDPOINT = ((import.meta.env.VITE_ASSET_ENDPOINT as string | undefined) ?? '').trim()

export function resolveAssetUrl(ref: string | null | undefined): string | null {
  if (!ref) return null
  if (/^(https?:)?\/\//i.test(ref)) return ref          // absolute / protocol-relative
  const path = ref.replace(/^\/+/, '')
  if (ASSET_ENDPOINT) {
    const ep = ASSET_ENDPOINT.startsWith('/') ? ASSET_ENDPOINT : `/${ASSET_ENDPOINT}`
    return `${API_BASE_URL}${ep}?path=${encodeURIComponent(path)}`
  }
  return `${API_BASE_URL}/${path}`                       // base-relative (mock default)
}

export function mapRichDocument(d: ApiRichDocument): RichDocument {
  const cover: DocCover = {
    projectName: d.cover.project_name,
    subtitle: d.cover.subtitle,
    version: d.cover.version,
    layer: d.cover.layer,
    group: d.cover.group,
    standard: d.cover.standard,
    process: d.cover.process,
    generatedAt: d.cover.generated_at,
  }
  const toc: TocEntry[] = (d.toc ?? []).map((t) => ({ id: t.id, number: t.number, title: t.title, level: t.level }))
  const meta: DocMeta = {
    pipelineDataAvailable: d.meta.pipeline_data_available,
    modelDataAvailable: d.meta.model_data_available,
    source: d.meta.source === 'pipeline' ? 'pipeline' : 'model',
    layers: d.meta.layers ?? [],
    components: d.meta.components ?? [],
    unitsTotal: d.meta.units_total ?? 0,
    functionsTotal: d.meta.functions_total ?? 0,
    globalsTotal: d.meta.globals_total ?? 0,
  }
  const ts = d.test_summary
  const testSummary: TestSummary | null = ts ? {
    units: ts.units,
    functionSpecs: ts.function_specs,
    dynamicSpecs: ts.dynamic_specs,
    mocks: ts.mocks,
    equipment: ts.equipment,
    platform: ts.platform,
  } : null
  return { cover, toc, sections: (d.sections ?? []).map(mapRichSection), meta, testSummary }
}

/** A13: counts per review state, and how many need a reviewer or carried their approval. */
export function mapDocStats(s: Record<string, number>): DocStats {
  return {
    total: s.total ?? 0,
    inReview: s.in_review ?? 0,
    submitted: s.submitted ?? 0,
    changesRequested: s.changes_requested ?? 0,
    approved: s.approved ?? 0,
    needsReviewer: s.needs_reviewer ?? 0,
    carried: s.carried ?? 0,
  }
}
