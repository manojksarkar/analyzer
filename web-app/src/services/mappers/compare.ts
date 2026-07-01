import type {
  CompareResult, CompareDocumentDetail, CompareDocumentDiff, CompareBlock,
  CompareRichSection, DiffType, DiffMark,
} from '../../types'
import { resolveAssetUrl } from './document'

export function mapCompare(r: {
  current: CompareResult['current']
  baseline: CompareResult['baseline']
  summary: CompareResult['summary']
  changed_documents: { document_id: string; name: string; process: string; diff_type: string; sections_changed: string[] }[]
}): CompareResult {
  return {
    current: r.current,
    baseline: r.baseline,
    summary: r.summary,
    changedDocuments: (r.changed_documents ?? []).map((d) => ({
      documentId: d.document_id, name: d.name, process: d.process,
      diffType: d.diff_type as CompareResult['changedDocuments'][number]['diffType'],
      sectionsChanged: d.sections_changed,
    })),
  }
}

export function mapCompareDetail(r: {
  document_name: string
  sections: { key: string; title: string; diff_type: string; current_content: string; baseline_content: string }[]
}): CompareDocumentDetail {
  return {
    documentName: r.document_name,
    sections: (r.sections ?? []).map((s) => ({
      key: s.key, title: s.title,
      diffType: s.diff_type as CompareDocumentDetail['sections'][number]['diffType'],
      currentContent: s.current_content, baselineContent: s.baseline_content,
    })),
  }
}

/* ── Rich, highlight-annotated compare diff ── */

interface ApiDiffSegment { text: string; mark?: string }

interface ApiCompareBlock {
  kind: string
  segments?: ApiDiffSegment[]
  label?: string
  headers?: string[]
  rows?: string[][]
  row_marks?: string[]
  cell_marks?: string[][]
  image_url?: string | null
  mermaid?: string | null
  caption?: string | null
  changed?: boolean
}

interface ApiRichDiffSection {
  id: string
  number: string
  title: string
  level: number
  diff_type: string
  source?: { artifact?: string; present?: string }
  current_blocks?: ApiCompareBlock[]
  baseline_blocks?: ApiCompareBlock[]
}

interface ApiCompareDocDiff {
  mode?: string
  document_name: string
  current?: { ref?: string | null; version?: string | null; branch?: string | null; short_sha?: string | null; has_snapshot?: boolean }
  baseline?: { ref?: string | null; version?: string | null; branch?: string | null; short_sha?: string | null; has_snapshot?: boolean }
  summary?: { added: number; changed: number; removed: number; unchanged: number }
  sections?: (ApiRichDiffSection | { key: string; title: string; diff_type: string; current_content: string; baseline_content: string })[]
}

function mapBlock(b: ApiCompareBlock): CompareBlock {
  switch (b.kind) {
    case 'table':
      return {
        kind: 'table',
        headers: b.headers ?? [],
        rows: b.rows ?? [],
        rowMarks: (b.row_marks ?? []) as DiffMark[],
        cellMarks: (b.cell_marks ?? []) as DiffMark[][],
      }
    case 'diagram':
      return {
        kind: 'diagram',
        imageUrl: resolveAssetUrl(b.image_url),
        mermaid: b.mermaid ?? null,
        caption: b.caption ?? null,
        changed: !!b.changed,
      }
    case 'keyvalue':
      return {
        kind: 'keyvalue',
        label: b.label ?? '',
        segments: (b.segments ?? []).map((s) => ({ text: s.text, mark: (s.mark ?? 'none') as DiffMark })),
      }
    case 'text':
    default:
      return {
        kind: 'text',
        segments: (b.segments ?? []).map((s) => ({ text: s.text, mark: (s.mark ?? 'none') as DiffMark })),
      }
  }
}

function mapRichDiffSection(s: ApiRichDiffSection): CompareRichSection {
  return {
    id: s.id,
    number: s.number ?? '',
    title: s.title ?? '',
    level: s.level ?? 1,
    diffType: s.diff_type as DiffType,
    source: {
      artifact: s.source?.artifact ?? '',
      present: (s.source?.present ?? 'both') as CompareRichSection['source']['present'],
    },
    currentBlocks: (s.current_blocks ?? []).map(mapBlock),
    baselineBlocks: (s.baseline_blocks ?? []).map(mapBlock),
  }
}

export function mapCompareDocumentDiff(r: ApiCompareDocDiff): CompareDocumentDiff {
  const isRich = r.mode === 'rich'
  const rawSections = r.sections ?? []
  return {
    mode: isRich ? 'rich' : 'flat',
    documentName: r.document_name,
    current: r.current && {
      ref: r.current.ref ?? null, version: r.current.version ?? null,
      branch: r.current.branch ?? null, shortSha: r.current.short_sha ?? null,
      hasSnapshot: !!r.current.has_snapshot,
    },
    baseline: r.baseline && {
      ref: r.baseline.ref ?? null, version: r.baseline.version ?? null,
      branch: r.baseline.branch ?? null, shortSha: r.baseline.short_sha ?? null,
      hasSnapshot: !!r.baseline.has_snapshot,
    },
    summary: r.summary,
    sections: isRich ? (rawSections as ApiRichDiffSection[]).map(mapRichDiffSection) : [],
    flatSections: isRich ? [] : (rawSections as { key: string; title: string; diff_type: string; current_content: string; baseline_content: string }[]).map((s) => ({
      key: s.key, title: s.title, diffType: s.diff_type as DiffType,
      currentContent: s.current_content, baselineContent: s.baseline_content,
    })),
  }
}
