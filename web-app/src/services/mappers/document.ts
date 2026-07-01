import { z } from 'zod'
import type {
  Document, DocStats, DocStatus, DocumentDetail, SectionReviewState,
  RichDocument, RichSection, RichSectionType, TocEntry, DocCover, DocMeta,
  FlowchartTableData, BehaviorTableData,
} from '../../types'
import { formatShortDate, avatarPalette } from '../../lib/format'
import { API_BASE_URL } from '../../lib/http'

export const ApiAssigneeSchema = z.object({
  user_id: z.string(), name: z.string(), initials: z.string(),
})
export type ApiAssignee = z.infer<typeof ApiAssigneeSchema>

export const ApiDocumentSchema = z.object({
  id: z.string(), name: z.string(), subtitle: z.string(), process: z.string(),
  layer: z.string(), group: z.string(), status: z.string(), version_id: z.string(),
  due_date: z.string().nullable(), assignees: z.array(ApiAssigneeSchema),
  created_at: z.string(), updated_at: z.string(),
})
export type ApiDocument = z.infer<typeof ApiDocumentSchema>

export const ApiDocSectionSchema = z.object({
  key: z.string(), title: z.string(), order: z.number(), content: z.string(),
  review_state: z.string().nullable(), reviewed_by: z.string().nullable(), reviewed_at: z.string().nullable(),
})
export type ApiDocSection = z.infer<typeof ApiDocSectionSchema>

export const ApiDocumentDetailSchema = ApiDocumentSchema.extend({
  sections: z.array(ApiDocSectionSchema).optional(),
  review_progress: z.object({ resolved: z.number(), total: z.number() }).optional(),
})
export type ApiDocumentDetail = z.infer<typeof ApiDocumentDetailSchema>

/**
 * @param versionTagById optional version_id → tag lookup so the UI can show
 * "v1.2.0" instead of the raw "ver3" id when the caller has versions cached.
 */
export function mapDocument(d: ApiDocument, versionTagById?: Record<string, string>): Document {
  const a = d.assignees?.[0]
  const pal = a ? avatarPalette(a.user_id) : undefined
  return {
    id: d.id,
    name: d.name,
    process: d.process,
    status: d.status as DocStatus,
    version: versionTagById?.[d.version_id] ?? d.version_id,
    updatedAt: formatShortDate(d.updated_at) ?? '',
    subtitle: d.subtitle || undefined,
    due: formatShortDate(d.due_date) ?? undefined,
    assignee: a?.name,
    assigneeInitials: a?.initials,
    assigneeColor: pal?.bg,
    assigneeTextColor: pal?.text,
  }
}

/** Document + its section bodies (GET …/documents/{id}). */
export function mapDocumentDetail(
  d: ApiDocumentDetail,
  versionTagById?: Record<string, string>,
): DocumentDetail {
  const sections = (d.sections ?? [])
    .slice()
    .sort((a, b) => a.order - b.order)
    .map((s) => ({
      key: s.key,
      title: s.title,
      order: s.order,
      content: s.content,
      reviewState: (s.review_state as SectionReviewState | null) ?? null,
      reviewedBy: s.reviewed_by,
      reviewedAt: s.reviewed_at,
    }))
  return {
    ...mapDocument(d, versionTagById),
    sections,
    reviewProgress: d.review_progress,
  }
}

/* ── Rich render payload ── */

const ApiFlowchartSchema = z.object({
  image_url: z.string().nullable().optional(),
  mermaid: z.string().nullable().optional(),
  label: z.string(),
})

const ApiFlowchartTableSchema = z.object({
  description: z.string(),
  flowcharts: z.array(ApiFlowchartSchema),
  risk: z.string(),
  capacity: z.string(),
  input_name: z.string(),
  output_name: z.string(),
})
type ApiFlowchartTable = z.infer<typeof ApiFlowchartTableSchema>

const ApiBehaviorTableSchema = z.object({
  description_list: z.array(z.string()),
  risk: z.string(),
  capacity: z.string(),
  input_name: z.string(),
  output_name: z.string(),
  diagram_url: z.string().nullable().optional(),
})
type ApiBehaviorTable = z.infer<typeof ApiBehaviorTableSchema>

// Recursive section — the type is hand-declared and the schema is built with
// `z.lazy` so it can reference itself (zod can't infer a self-referential type).
interface ApiRichSection {
  id: string; number: string; title: string; level: number; type: string
  content: string | null; table: { headers: string[]; rows: string[][] } | null
  image_url?: string | null; mermaid?: string | null
  children: ApiRichSection[]
  flowchart_table?: ApiFlowchartTable | null
  behavior_table?: ApiBehaviorTable | null
}
const ApiRichSectionSchema: z.ZodType<ApiRichSection> = z.lazy(() =>
  z.object({
    id: z.string(), number: z.string(), title: z.string(), level: z.number(), type: z.string(),
    content: z.string().nullable(),
    table: z.object({ headers: z.array(z.string()), rows: z.array(z.array(z.string())) }).nullable(),
    image_url: z.string().nullable().optional(),
    mermaid: z.string().nullable().optional(),
    children: z.array(ApiRichSectionSchema),
    flowchart_table: ApiFlowchartTableSchema.nullable().optional(),
    behavior_table: ApiBehaviorTableSchema.nullable().optional(),
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
})
export type ApiRichDocument = z.infer<typeof ApiRichDocumentSchema>

function mapRichSection(s: ApiRichSection): RichSection {
  let flowchartTable: FlowchartTableData | null = null
  if (s.flowchart_table) {
    const ft = s.flowchart_table
    flowchartTable = {
      description: ft.description,
      flowcharts: (ft.flowcharts ?? []).map((fc) => ({
        imageUrl: resolveAssetUrl(fc.image_url),
        mermaid: fc.mermaid ?? null,
        label: fc.label ?? '',
      })),
      risk: ft.risk,
      capacity: ft.capacity,
      inputName: ft.input_name,
      outputName: ft.output_name,
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
    }
  }

  return {
    id: s.id,
    number: s.number,
    title: s.title,
    level: s.level,
    type: (s.type as RichSectionType) ?? 'richtext',
    content: s.content,
    table: s.table,
    imageUrl: resolveAssetUrl(s.image_url),
    mermaid: s.mermaid ?? null,
    children: (s.children ?? []).map(mapRichSection),
    flowchartTable,
    behaviorTable,
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
  return { cover, toc, sections: (d.sections ?? []).map(mapRichSection), meta }
}

export function mapDocStats(s: Record<string, number>): DocStats {
  return {
    total: s.total ?? 0,
    approved: s.approved ?? 0,
    inReview: s.in_review ?? 0,
    never: s.never ?? 0,
    unchanged: s.unchanged ?? 0,
  }
}
