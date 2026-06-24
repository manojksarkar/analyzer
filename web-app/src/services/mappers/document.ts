import type {
  Document, DocStats, DocStatus, DocumentDetail, SectionReviewState,
  RichDocument, RichSection, RichSectionType, TocEntry, DocCover, DocMeta,
} from '../../types'
import { formatShortDate, avatarPalette } from '../../lib/format'
import { API_BASE_URL } from '../../lib/http'

export interface ApiAssignee { user_id: string; name: string; initials: string }
export interface ApiDocument {
  id: string; name: string; subtitle: string; process: string; layer: string; group: string
  status: string; version_id: string; due_date: string | null
  assignees: ApiAssignee[]; created_at: string; updated_at: string
}

export interface ApiDocSection {
  key: string; title: string; order: number; content: string
  review_state: string | null; reviewed_by: string | null; reviewed_at: string | null
}
export interface ApiDocumentDetail extends ApiDocument {
  sections?: ApiDocSection[]
  review_progress?: { resolved: number; total: number }
}

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

interface ApiRichSection {
  id: string; number: string; title: string; level: number; type: string
  content: string | null; table: { headers: string[]; rows: string[][] } | null
  image_url?: string | null; mermaid?: string | null
  children: ApiRichSection[]
}
export interface ApiRichDocument {
  cover: {
    project_name: string; subtitle: string; version: string; layer: string; group: string
    standard?: string; process?: string; generated_at?: string
  }
  toc: { id: string; number: string; title: string; level: number }[]
  sections: ApiRichSection[]
  meta: {
    pipeline_data_available: boolean; model_data_available: boolean
    source: string; layers: string[]; components: string[]
    units_total: number; functions_total: number; globals_total: number
  }
}

function mapRichSection(s: ApiRichSection): RichSection {
  return {
    id: s.id,
    number: s.number,
    title: s.title,
    level: s.level,
    type: (s.type as RichSectionType) ?? 'richtext',
    content: s.content,
    table: s.table,
    // The API returns a base-relative asset path; resolve it to an absolute URL
    // (the diagram route is unauthenticated, so an <img> can load it directly).
    imageUrl: s.image_url ? `${API_BASE_URL}/${s.image_url}` : null,
    mermaid: s.mermaid ?? null,
    children: (s.children ?? []).map(mapRichSection),
  }
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
