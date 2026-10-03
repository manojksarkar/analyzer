import { useState, useMemo, Fragment } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import {
  useVersions, useCommits, useDocuments, useDocument,
} from '../hooks/useProjects'
import { useProjectViewState } from '../hooks/useProjectViewState'
import { useCompareDocuments, useCompareDocumentDetail } from '../hooks/useCompare'
import { Avatar, Icon, Skeleton, CompareSectionSkeleton, StatusBadge } from '../components/ui'
import { cn } from '../lib/cn'
import { parseSectionBody } from '../lib/markdown'
import type {
  DiffType, DiffMark, DiffSegment, CompareBlock,
  CompareRichSection, Document,
} from '../types'

type TreeMode = 'diff' | 'all'

/* ─── Diff-type chip styling ─── */
const DIFF_BADGE: Record<DiffType, { label: string; cls: string; dot: string }> = {
  added:     { label: 'added',     cls: 'text-on-tertiary-container bg-[rgba(0,165,114,.1)]', dot: 'bg-on-tertiary-container' },
  changed:   { label: 'changed',   cls: 'text-secondary bg-secondary/10',                     dot: 'bg-secondary' },
  removed:   { label: 'removed',   cls: 'text-error bg-error-container',                       dot: 'bg-error' },
  unchanged: { label: 'unchanged', cls: 'text-on-surface-variant bg-surface-container',        dot: 'bg-outline-variant' },
}

/* ─── Inline highlight styling by change mark ─── */
const MARK_INLINE: Record<DiffMark, string> = {
  none:   '',
  add:    'bg-[rgba(0,165,114,.18)] text-on-tertiary-container rounded-[2px] px-px',
  del:    'bg-error-container text-error line-through rounded-[2px] px-px',
  change: 'bg-[#fff1cc] text-[#92600a] rounded-[2px] px-px',
}
const MARK_CELL: Record<DiffMark, string> = {
  none:   '',
  add:    'bg-[rgba(0,165,114,.14)]',
  del:    'bg-error-container/70 line-through',
  change: 'bg-[#fff4d6]',
}

/* ─── Section accent (left stripe at the gutter) by the kind of change ─── */
function sectionAccent(diffType: DiffType): string {
  if (diffType === 'unchanged') return ''
  if (diffType === 'added')   return 'border-l-[3px] border-l-on-tertiary-container bg-[rgba(0,165,114,.03)]'
  if (diffType === 'removed') return 'border-l-[3px] border-l-error bg-error-container/30'
  return 'border-l-[3px] border-l-secondary bg-surface-container-low'
}

/* ─── Inline word-level highlighted text ─── */
function Segments({ segments }: { segments: DiffSegment[] }) {
  if (!segments.length) return null
  return (
    <>
      {segments.map((s, i) =>
        s.mark === 'none'
          ? <span key={i}>{s.text}</span>
          : <span key={i} className={MARK_INLINE[s.mark]}>{s.text}</span>,
      )}
    </>
  )
}

/* ─── Mermaid / diagram block with a "changed" badge + source toggle ─── */
function DiffDiagramBlock({ block }: { block: Extract<CompareBlock, { kind: 'diagram' }> }) {
  const [showSrc, setShowSrc] = useState(false)
  return (
    <figure className={cn(
      'bg-surface-container-low border rounded-lg overflow-hidden',
      block.changed ? 'border-secondary/60' : 'border-outline-variant',
    )}>
      {block.imageUrl ? (
        <img src={block.imageUrl} alt={block.caption ?? 'Diagram'} loading="lazy"
             className="block w-full max-h-[400px] object-contain bg-white" />
      ) : (
        <div className="flex flex-col items-center justify-center text-center py-10 gap-2">
          <Icon name="account_tree" size={32} className="text-outline-variant" />
          <span className="font-mono text-caption text-on-surface-variant">{block.caption ?? 'Diagram'}</span>
        </div>
      )}
      <figcaption className="flex items-center justify-between gap-2 px-3 py-2 border-t border-outline-variant bg-white">
        <span className="flex items-center gap-1.5 font-mono text-label text-on-surface-variant truncate">
          {block.changed && <span className="px-1.5 py-0.5 rounded bg-secondary/10 text-secondary font-semibold">diagram changed</span>}
          <span className="truncate">{block.caption ?? 'Diagram'}</span>
        </span>
        {block.mermaid && (
          <button onClick={() => setShowSrc((v) => !v)}
                  className="flex items-center gap-1 flex-shrink-0 text-secondary hover:underline font-mono text-label">
            <Icon name="code" size={12} />{showSrc ? 'Hide source' : 'View source'}
          </button>
        )}
      </figcaption>
      {showSrc && block.mermaid && (
        <pre className="px-3 py-2 bg-surface-container-low border-t border-outline-variant overflow-x-auto font-mono text-label text-on-surface-variant whitespace-pre">{block.mermaid}</pre>
      )}
    </figure>
  )
}

/* ─── One diff block (text | keyvalue | table | diagram) ─── */
function DiffBlockView({ block }: { block: CompareBlock }) {
  if (block.kind === 'text') {
    return (
      <p className="text-sm text-on-surface leading-relaxed whitespace-pre-line">
        <Segments segments={block.segments} />
      </p>
    )
  }
  if (block.kind === 'keyvalue') {
    return (
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-mono text-caption text-on-surface-variant flex-shrink-0">{block.label}:</span>
        <span className="text-on-surface"><Segments segments={block.segments} /></span>
      </div>
    )
  }
  if (block.kind === 'diagram') {
    return <DiffDiagramBlock block={block} />
  }
  // table
  return (
    <div className="overflow-x-auto border border-outline-variant rounded-lg">
      <table className="w-full text-left text-xs">
        <thead className="bg-surface-container text-on-surface-variant">
          <tr>
            {block.headers.map((h, hi) => (
              <th key={hi} className="px-3 py-2.5 border-b border-outline-variant font-semibold whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((r, ri) => {
            const rowMark = block.rowMarks[ri] ?? 'none'
            return (
              <tr key={ri} className={cn('border-b border-[rgba(196,198,205,.6)]', rowMark !== 'none' && rowMark !== 'change' && MARK_CELL[rowMark])}>
                {r.map((c, ci) => {
                  const cellMark = block.cellMarks[ri]?.[ci] ?? 'none'
                  return (
                    <td key={ci} className={cn(
                      'px-3 py-2 align-top',
                      ci === 0 ? 'text-secondary font-mono text-caption' : 'text-on-surface-variant',
                      MARK_CELL[cellMark],
                    )}>{c}</td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ─── A pane's stack of blocks (or an empty-side placeholder) ─── */
function BlocksPane({ blocks, emptyLabel }: { blocks: CompareBlock[]; emptyLabel: string }) {
  if (!blocks.length) {
    return <p className="text-on-surface-variant italic text-sm">{emptyLabel}</p>
  }
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => <DiffBlockView key={i} block={b} />)}
    </div>
  )
}

/* ─── Flat-fallback markdown body → richtext / table blocks (legacy) ─── */
function SectionBody({ content }: { content: string }) {
  const blocks = parseSectionBody(content)
  if (blocks.length === 0) {
    return <p className="text-on-surface-variant italic text-sm">No content.</p>
  }
  return (
    <div className="space-y-3">
      {blocks.map((b, i) =>
        b.type === 'table' ? (
          <div key={i} className="overflow-hidden border border-outline-variant rounded-lg">
            <table className="w-full text-left text-xs">
              <thead className="bg-surface-container text-on-surface-variant">
                <tr>
                  {b.headers.map((h, hi) => (
                    <th key={hi} className="px-3 py-2.5 border-b border-outline-variant font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri} className="border-b border-[rgba(196,198,205,.6)]">
                    {r.map((c, ci) => (
                      <td key={ci} className={cn('px-3 py-2', ci === 0 ? 'text-secondary font-mono text-caption' : 'text-on-surface-variant')}>{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p key={i} className="text-on-surface leading-relaxed text-sm whitespace-pre-line">{b.text}</p>
        ),
      )}
    </div>
  )
}

/* ─── Left document tree (Diff / All) ─── */
// `process` tells a component's two documents apart: its SWE.3 and SWE.4 share its name.
interface TreeRow { id: string; name: string; process?: string; diffType: DiffType; changed: boolean }

function DocTree({ rows, mode, setMode, activeId, onSelect, changedCount, total, loading }: {
  rows: TreeRow[]; mode: TreeMode; setMode: (m: TreeMode) => void
  activeId: string | null; onSelect: (id: string) => void
  changedCount: number; total: number; loading: boolean
}) {
  return (
    <aside className="w-60 flex-shrink-0 bg-white border-r border-outline-variant flex flex-col overflow-hidden">
      <div className="px-3 py-2.5 border-b border-outline-variant flex-shrink-0 flex items-center justify-between">
        <span className="text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.1em]">Documents</span>
        <div className="flex items-center rounded-lg border border-outline-variant overflow-hidden font-mono text-label font-semibold">
          <button onClick={() => setMode('diff')} className={cn('px-2 py-1 transition-colors', mode === 'diff' ? 'bg-primary text-white' : 'text-on-surface-variant')}>Diff</button>
          <button onClick={() => setMode('all')} className={cn('px-2 py-1 transition-colors', mode === 'all' ? 'bg-primary text-white' : 'text-on-surface-variant')}>All</button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto py-2">
        {loading ? (
          <div className="px-2.5 space-y-2">
            {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-5" />)}
          </div>
        ) : rows.length === 0 ? (
          <div className="px-3 py-6 text-center text-outline font-mono text-caption">{mode === 'diff' ? 'No changed documents' : 'No documents'}</div>
        ) : (
          rows.map((d) => {
            const isActive = activeId === d.id
            return (
              <button
                key={d.id}
                onClick={() => onSelect(d.id)}
                className={cn(
                  'w-full flex items-center gap-1.5 transition-colors font-mono text-caption text-left border-l-2 py-[5px]',
                  isActive ? 'pl-2 pr-2.5 bg-surface-container text-secondary border-secondary' : 'px-2.5 border-transparent text-on-surface-variant hover:bg-surface-container-low',
                )}
              >
                <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', isActive ? 'bg-secondary' : d.changed ? DIFF_BADGE[d.diffType].dot : 'bg-outline-variant')} aria-hidden />
                <span className={cn('truncate', !d.changed && !isActive && 'opacity-40')}>{d.name}</span>
                {d.process && <span className={cn('ml-auto flex-shrink-0 text-label text-outline', !d.changed && !isActive && 'opacity-40')}>{d.process}</span>}
              </button>
            )
          })
        )}
      </div>
      <div className="px-3 py-2 border-t border-outline-variant flex-shrink-0">
        <span className="text-on-surface-variant font-mono text-caption">{changedCount} changed of {total}</span>
      </div>
    </aside>
  )
}

/* ─── The open document's review state: shown, never changed, here ─── */
// Compare is for reading changes. A document is reviewed and approved in the document itself
// (compare.html renderDocStateBar).
function DocStateBar({ doc, projectId }: { doc: Document; projectId: string }) {
  const carried = doc.review.carriedFrom
  return (
    <div className="flex-shrink-0 h-9 border-t border-outline-variant bg-white px-4 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2 min-w-0">
        <StatusBadge status={doc.status} suffix={carried ? ` · from ${carried.tag}` : undefined} />
        {doc.status !== 'approved' && (doc.reviewer ? (
          <span className="flex items-center gap-1.5 font-mono text-label text-outline whitespace-nowrap">
            <Avatar person={doc.reviewer} size={16} />Reviewer: {doc.reviewer.name}
          </span>
        ) : (
          <span className="font-mono text-label text-[#b45309] whitespace-nowrap">Needs a reviewer</span>
        ))}
      </div>
      <Link
        to={`/projects/${projectId}/documents/${doc.id}?tab=review`}
        className="font-mono text-caption font-medium text-secondary hover:underline whitespace-nowrap"
      >
        Review and approve in the document →
      </Link>
    </div>
  )
}

/* ─── A unified, render-ready section for the two-pane diff ─── */
interface PaneSection {
  key: string
  title: string
  number: string
  level: number
  diffType: DiffType
  sourceLabel: string
  /** rich blocks (mode 'rich') */
  current?: CompareBlock[]
  baseline?: CompareBlock[]
  /** flat markdown (mode 'flat') */
  currentText?: string
  baselineText?: string
}

export function ComparePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const pid = projectId ?? ''
  const [searchParams] = useSearchParams()

  const { data: versions } = useVersions(pid)
  const { data: commits } = useCommits(pid)
  const { selectedSha } = useProjectViewState(pid)

  /* Current ref = the shared Subbar picker selection (defaults to latest version) */
  const currentRef = selectedSha ?? versions?.[0]?.sha
  const currentVersion = versions?.find((v) => v.sha === currentRef)
  const currentCommit = commits?.find((c) => c.sha === currentRef)

  /* Baseline ref is FIXED by the selected current version (its predecessor) — not user-pickable */
  const currentIdx = versions?.findIndex((v) => v.sha === currentRef) ?? -1
  const baselineRef = currentIdx >= 0 ? versions?.[currentIdx + 1]?.sha : versions?.[1]?.sha
  const baselineVersion = versions?.find((v) => v.sha === baselineRef)
  const baselineCommit = commits?.find((c) => c.sha === baselineRef)

  const [treeMode, setTreeMode] = useState<TreeMode>('diff')
  const [pickedDocId, setPickedDocId] = useState<string | null>(null)
  const [changesOnly, setChangesOnly] = useState(false)

  const { data: compareDocs, isLoading: docsLoading } = useCompareDocuments(pid, currentRef, baselineRef)
  const { data: allDocs, isLoading: allDocsLoading } = useDocuments(pid, currentVersion?.id ? { versionId: currentVersion.id } : undefined)

  const changedSet = useMemo(() => new Set((compareDocs?.documents ?? []).map((d) => d.documentId)), [compareDocs])
  const changedById = useMemo(() => new Map((compareDocs?.documents ?? []).map((d) => [d.documentId, d])), [compareDocs])
  // Each current document's review state, shown beside it (never changed here).
  const docById = useMemo(() => new Map((allDocs ?? []).map((d) => [d.id, d])), [allDocs])

  /* Active doc = explicit pick, else ?doc= param (if changed), else first changed doc */
  const paramDoc = searchParams.get('doc')
  const defaultDocId = (paramDoc && changedSet.has(paramDoc) ? paramDoc : undefined) ?? compareDocs?.documents?.[0]?.documentId ?? null
  const activeDocId = pickedDocId ?? defaultDocId

  const { data: detail, isLoading: detailLoading } = useCompareDocumentDetail(pid, activeDocId ?? undefined, currentRef, baselineRef)
  // The open document's review state, shown under it (read-only here). Only for a document of
  // the Current side: a removed one is the reference's.
  const { data: docDetail } = useDocument(pid, activeDocId ?? '')
  const stateDoc = docDetail && currentVersion?.id && docDetail.versionId === currentVersion.id ? docDetail : undefined

  const isRich = detail?.mode === 'rich'

  /* Unify rich + flat into one render-ready section list. */
  const sections: PaneSection[] = useMemo(() => {
    if (!detail) return []
    if (detail.mode === 'rich') {
      return detail.sections.map((s: CompareRichSection) => ({
        key: s.id,
        title: s.title,
        number: s.number,
        level: s.level,
        diffType: s.diffType,
        sourceLabel: s.source.artifact,
        current: s.currentBlocks,
        baseline: s.baselineBlocks,
      }))
    }
    return detail.flatSections.map((s) => ({
      key: s.key,
      title: s.title,
      number: '',
      level: 1,
      diffType: s.diffType,
      sourceLabel: 'Interface table',
      currentText: s.currentContent,
      baselineText: s.baselineContent,
    }))
  }, [detail])

  const changedSections = sections.filter((s) => s.diffType !== 'unchanged')
  const total = changedSections.length
  const visibleSections = changesOnly ? changedSections : sections

  // A removed document exists only in the baseline, so it is not in `allDocs` (the current
  // version's list). "All" lists it too, and the total counts it — the footer read
  // "10 changed of 3" when ten documents were removed and three kept.
  const removedRows: TreeRow[] = useMemo(() => (compareDocs?.documents ?? [])
    .filter((d) => d.diffType === 'removed')
    .map((d) => ({ id: d.documentId, name: d.name, process: d.process, diffType: d.diffType, changed: true })), [compareDocs])
  const treeRows: TreeRow[] = useMemo(() => {
    if (treeMode === 'diff') {
      return (compareDocs?.documents ?? []).map((d) => ({ id: d.documentId, name: d.name, process: d.process, diffType: d.diffType, changed: true }))
    }
    return [
      ...(allDocs ?? []).map((d) => ({
        id: d.id, name: d.name, process: d.process,
        diffType: changedById.get(d.id)?.diffType ?? 'unchanged',
        changed: changedSet.has(d.id),
      })),
      ...removedRows,
    ]
  }, [treeMode, compareDocs, allDocs, changedById, changedSet, removedRows])
  const changedCount = changedSet.size
  const totalCount = allDocs ? allDocs.length + removedRows.length : changedCount

  function selectDoc(id: string) {
    setPickedDocId(id)
  }

  const docTitle = detail?.documentName ?? docDetail?.name ?? changedById.get(activeDocId ?? '')?.name ?? 'Document'
  const currentTag = currentVersion?.tag ?? currentCommit?.versionTag
  const currentBranch = currentCommit?.branch ?? currentVersion?.branch ?? 'main'
  const currentShort = currentCommit?.shortSha ?? currentVersion?.shortSha ?? currentRef?.slice(0, 7) ?? '—'
  const baselineShort = baselineCommit?.shortSha ?? baselineVersion?.shortSha ?? baselineRef?.slice(0, 7) ?? '—'
  const isLatest = currentVersion && versions?.[0]?.sha === currentVersion.sha

  return (
    <div className="flex h-full overflow-hidden">
      <DocTree
        rows={treeRows} mode={treeMode} setMode={setTreeMode}
        activeId={activeDocId} onSelect={selectDoc}
        changedCount={changedCount} total={totalCount}
        loading={treeMode === 'diff' ? docsLoading && !compareDocs : allDocsLoading && !allDocs}
      />

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {docsLoading && !compareDocs ? (
          /* ─── Loading the diff list ─── */
          <div className="flex-1 overflow-y-auto bg-surface-container-low">
            <div className="bg-white border-b border-outline-variant px-8 pt-7 pb-5 space-y-3">
              <Skeleton className="h-3 w-40" />
              <Skeleton className="h-7 w-1/2" />
            </div>
            <CompareSectionSkeleton />
          </div>
        ) : !activeDocId ? (
          /* ─── Empty state ─── */
          <div className="flex-1 flex items-center justify-center p-8 bg-surface-container-low overflow-y-auto">
            <div className="text-center max-w-[480px]">
              <div className="w-16 h-16 rounded-2xl bg-surface-container flex items-center justify-center mx-auto mb-5">
                <Icon name="difference" size={32} className="text-on-surface-variant" />
              </div>
              {/* Nothing changed (or nothing to compare against) says so; it pointed at "a
                  changed document below" with nothing below. */}
              <h2 className="text-on-surface font-semibold text-lg mb-2">
                {!baselineRef ? 'Nothing to compare yet'
                  : compareDocs && compareDocs.documents.length === 0 ? 'No changes between these versions'
                    : 'Select a document to compare'}
              </h2>
              <p className="text-on-surface-variant text-xs mb-1">
                Reference <span className="font-mono text-outline">{baselineShort}</span> → Current <span className="font-mono text-on-tertiary-container">{currentBranch} @ {currentShort}</span>
              </p>
              <p className="text-outline text-xs mb-8">
                {!baselineRef ? 'This project has one version. Run analysis on another commit to compare the two.'
                  : compareDocs && compareDocs.documents.length === 0 ? 'Every document is the same in both. Pick one on the left to read it.'
                    : 'Pick a document from the left panel, or a changed document below.'}
              </p>
              <div className="text-left space-y-2">
                {(compareDocs?.documents ?? []).map((d) => (
                  <button
                    key={d.documentId}
                    onClick={() => selectDoc(d.documentId)}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 bg-white border border-outline-variant rounded-lg hover:border-secondary transition-colors text-left"
                  >
                    <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', DIFF_BADGE[d.diffType].dot)} aria-hidden />
                    <span className="text-on-surface text-sm flex-1 truncate">{d.name}</span>
                    <span className="font-mono text-label text-outline flex-shrink-0">{d.process}</span>
                    {docById.get(d.documentId) && <StatusBadge status={docById.get(d.documentId)!.status} size="sm" />}
                    <span className={cn('px-1.5 py-0.5 rounded font-mono text-caption', DIFF_BADGE[d.diffType].cls)}>{DIFF_BADGE[d.diffType].label}</span>
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          <>
            {/* Single scroller — the 2-col grid keeps each section's two sides the
                same height, so they scroll together AND stay aligned even when one
                side has much more content (the shorter side gets filler whitespace). */}
            <div className="flex-1 overflow-y-auto bg-surface-container-low min-h-0">
              <div className="grid grid-cols-2 items-stretch">
                {/* Sticky pane headers */}
                <div className="sticky top-0 z-10 bg-white border-b border-r border-outline-variant px-4 py-2 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full bg-outline-variant flex-shrink-0" aria-hidden />
                  <span className="text-on-surface font-mono text-xs font-medium">Reference</span>
                  <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant border border-outline-variant uppercase font-mono text-micro font-bold">{baselineVersion?.tag ?? baselineShort}</span>
                  <span className="ml-auto flex items-center gap-1 text-secondary font-mono text-caption">
                    <span className="w-1.5 h-1.5 rounded-sm bg-secondary inline-block" aria-hidden />{total} changed
                  </span>
                </div>
                <div className="sticky top-0 z-10 bg-white border-b border-outline-variant px-4 py-2 flex items-center gap-2">
                  <span className="w-2 h-2 rounded-full flex-shrink-0 bg-on-tertiary-container" aria-hidden />
                  <span className="text-on-surface font-mono text-xs font-medium">Current</span>
                  {isLatest && <span className="px-2 py-0.5 rounded uppercase font-mono text-micro font-bold bg-on-tertiary-container text-white">Latest</span>}
                  <span className="text-on-surface-variant font-mono text-caption">{currentTag ? currentTag : `${currentBranch} @ ${currentShort}`}</span>
                  <div className="ml-auto flex items-center gap-2">
                    <button
                      onClick={() => setChangesOnly((v) => !v)}
                      className={cn('flex items-center gap-1 px-2 py-0.5 rounded border font-mono text-label transition-colors',
                        changesOnly ? 'bg-primary text-white border-primary' : 'border-outline-variant text-on-surface-variant hover:bg-surface-container-low')}
                      title="Show only changed sections"
                    >
                      <Icon name="filter_alt" size={11} />Changes only
                    </button>
                    {currentVersion && currentVersion.status !== 'draft' && (
                      <span title="The version's status — derived from its documents">
                        <StatusBadge status={currentVersion.status} size="sm" />
                      </span>
                    )}
                  </div>
                </div>

                {/* Document title row (one cell per side) */}
                <div className="bg-white border-r border-b border-outline-variant/60 px-8 pt-7 pb-5">
                  <p className="text-on-surface-variant uppercase mb-1 font-mono text-caption tracking-[0.1em]">{baselineShort}</p>
                  <h1 className="text-primary font-semibold font-sans text-2xl">{docTitle}</h1>
                  <p className="text-on-surface-variant mt-0.5 text-xs">Software Detailed Design Specification</p>
                </div>
                <div className="bg-white border-b border-outline-variant/60 px-8 pt-7 pb-5">
                  <p className="text-on-surface-variant uppercase mb-1 font-mono text-caption tracking-[0.1em]">{currentShort}</p>
                  <h1 className="text-primary font-semibold font-sans text-2xl">{docTitle}</h1>
                  <p className="text-on-surface-variant mt-0.5 text-xs">Software Detailed Design Specification</p>
                </div>

                {/* Per-section rows — grid auto-row height = the taller side, so the
                    two cells of a row start at the same Y (filler on the shorter one). */}
                {detailLoading && sections.length === 0 ? (
                  <div className="col-span-2"><CompareSectionSkeleton /></div>
                ) : visibleSections.length === 0 ? (
                  <div className="col-span-2 bg-white px-8 py-16 text-center text-on-surface-variant font-mono text-caption">
                    {changesOnly ? 'No changed sections' : 'No content'}
                  </div>
                ) : (
                  visibleSections.map((s) => {
                    const changed = s.diffType !== 'unchanged'
                    const headingSize = s.level <= 1 ? 'text-lg' : s.level === 2 ? 'text-base' : 'text-sm'
                    return (
                      <Fragment key={s.key}>
                        {/* Reference cell */}
                        <div className={cn('bg-white border-r border-b border-outline-variant/60 px-8 py-6',
                          s.diffType === 'removed' ? 'bg-error-container/20' : changed && 'opacity-90')}>
                          <div className="flex items-baseline gap-2 mb-3">
                            {s.number && <span className="font-mono text-caption text-outline flex-shrink-0">{s.number}</span>}
                            <h2 className={cn('text-primary font-semibold font-sans', headingSize)}>{s.title}</h2>
                          </div>
                          {isRich
                            ? <BlocksPane blocks={s.baseline ?? []} emptyLabel={s.diffType === 'added' ? 'New in current — not present in reference.' : 'No content.'} />
                            : <SectionBody content={s.baselineText ?? ''} />}
                        </div>
                        {/* Current cell */}
                        <div className={cn('bg-white border-b border-outline-variant/60 px-8 py-6 transition-all', sectionAccent(s.diffType))}>
                          <div className="flex items-baseline gap-2 min-w-0 mb-3">
                            {s.number && <span className="font-mono text-caption text-outline flex-shrink-0">{s.number}</span>}
                            <h2 className={cn('text-primary font-semibold font-sans', headingSize)}>{s.title}</h2>
                          </div>
                          {changed && (
                            <div className="flex items-center gap-1.5 mb-3">
                              <span className={cn('px-1.5 py-0.5 rounded font-mono text-caption', DIFF_BADGE[s.diffType].cls)}>{DIFF_BADGE[s.diffType].label}</span>
                              {s.sourceLabel && (
                                <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded font-mono text-caption text-on-surface-variant bg-surface-container-low border border-outline-variant">
                                  <Icon name="source" size={11} />{s.sourceLabel}
                                </span>
                              )}
                            </div>
                          )}
                          {isRich
                            ? <BlocksPane blocks={s.current ?? []} emptyLabel={s.diffType === 'removed' ? 'Removed — not present in current.' : 'No content.'} />
                            : <SectionBody content={s.currentText ?? ''} />}
                        </div>
                      </Fragment>
                    )
                  })
                )}
              </div>
            </div>

            {/* The document's review state, read-only: it is reviewed in the document */}
            {stateDoc && <DocStateBar doc={stateDoc} projectId={pid} />}
          </>
        )}
      </div>
    </div>
  )
}
