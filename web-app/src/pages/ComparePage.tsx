import { useState, useMemo, Fragment } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  useVersions, useCommits, useDocuments, useDocument,
} from '../hooks/useProjects'
import { useProjectViewState } from '../hooks/useProjectViewState'
import { useCompareDocuments, useCompareDocumentDetail } from '../hooks/useCompare'
import { useReviewSection, useApproveDoc, useSubmitReview } from '../hooks/useDocumentMutations'
import { Icon } from '../components/ui'
import { cn } from '../lib/cn'
import { parseSectionBody } from '../lib/markdown'
import type {
  DiffType, SectionReviewState, DiffMark, DiffSegment, CompareBlock,
  CompareRichSection,
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

/* ─── Section accent (left stripe at the gutter) by review state, else "changed" blue ─── */
function sectionAccent(diffType: DiffType, review: SectionReviewState | null): string {
  if (diffType === 'unchanged') return ''
  if (review === 'accepted') return 'border-l-[3px] border-l-on-tertiary-container bg-[rgba(0,165,114,.04)]'
  if (review === 'declined') return 'border-l-[3px] border-l-outline-variant bg-surface-container-low'
  if (review === 'edited')   return 'border-l-[3px] border-l-secondary bg-[rgba(0,88,190,.04)]'
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
interface TreeRow { id: string; name: string; diffType: DiffType; changed: boolean }

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
          <div className="px-3 py-6 text-center text-outline font-mono text-caption">Loading…</div>
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

/* ─── Per-section review controls (current pane, changed sections) ─── */
function SectionControls({ review, onAccept, onDecline }: {
  review: SectionReviewState | null
  onAccept: () => void; onDecline: () => void
}) {
  return (
    <div className="flex-shrink-0 flex items-center gap-1.5 mt-0.5">
      {review && (
        <span className={cn(
          'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-label font-mono font-semibold border',
          review === 'accepted' ? 'bg-[rgba(0,165,114,.1)] text-on-tertiary-container border-[#86efac]'
            : review === 'edited' ? 'bg-secondary/10 text-secondary border-[#9cc3ff]'
            : 'bg-surface-container text-on-surface-variant border-outline-variant',
        )}>
          {review === 'accepted' ? 'Accepted' : review === 'edited' ? 'Edited' : 'Declined'}
        </span>
      )}
      <button onClick={onAccept} className="flex items-center gap-1 px-2 py-0.5 rounded border border-outline-variant hover:bg-on-tertiary-container hover:text-white hover:border-on-tertiary-container text-on-surface-variant transition-colors text-label font-mono">
        <Icon name="check" size={11} />Accept
      </button>
      <button onClick={onDecline} className="flex items-center gap-1 px-2 py-0.5 rounded border border-outline-variant hover:bg-surface-container-high text-on-surface-variant transition-colors text-label font-mono">
        <Icon name="remove" size={11} />Decline
      </button>
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
  reviewState: SectionReviewState | null
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
  /** Optimistic per-section review state, keyed by section id (rich sections
   *  don't round-trip through the stored-section table, so we track locally). */
  const [localReview, setLocalReview] = useState<Record<string, SectionReviewState>>({})

  const { data: compareDocs, isLoading: docsLoading } = useCompareDocuments(pid, currentRef, baselineRef)
  const { data: allDocs } = useDocuments(pid, currentVersion?.id ? { versionId: currentVersion.id } : undefined)

  const changedSet = useMemo(() => new Set((compareDocs?.documents ?? []).map((d) => d.documentId)), [compareDocs])
  const changedById = useMemo(() => new Map((compareDocs?.documents ?? []).map((d) => [d.documentId, d])), [compareDocs])

  /* Active doc = explicit pick, else ?doc= param (if changed), else first changed doc */
  const paramDoc = searchParams.get('doc')
  const defaultDocId = (paramDoc && changedSet.has(paramDoc) ? paramDoc : undefined) ?? compareDocs?.documents?.[0]?.documentId ?? null
  const activeDocId = pickedDocId ?? defaultDocId

  const { data: detail } = useCompareDocumentDetail(pid, activeDocId ?? undefined, currentRef, baselineRef)
  const { data: docDetail } = useDocument(pid, activeDocId ?? '')

  const reviewSection = useReviewSection(pid)
  const approveDoc = useApproveDoc(pid)
  const submitReview = useSubmitReview(pid)

  const isRich = detail?.mode === 'rich'

  /* Flat-fallback overlay: live doc detail (edited content + persisted review). */
  const liveByKey = useMemo(() => new Map((docDetail?.sections ?? []).map((s) => [s.key, s])), [docDetail])

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
        reviewState: localReview[s.id] ?? null,
        current: s.currentBlocks,
        baseline: s.baselineBlocks,
      }))
    }
    return detail.flatSections.map((s) => {
      const live = liveByKey.get(s.key)
      return {
        key: s.key,
        title: s.title,
        number: '',
        level: 1,
        diffType: s.diffType,
        sourceLabel: 'Interface table',
        reviewState: live?.reviewState ?? localReview[s.key] ?? null,
        currentText: live?.content ?? s.currentContent,
        baselineText: s.baselineContent,
      }
    })
  }, [detail, liveByKey, localReview])

  const changedSections = sections.filter((s) => s.diffType !== 'unchanged')
  const resolved = changedSections.filter((s) => s.reviewState).length
  const total = changedSections.length
  const reviewMode = docDetail?.status === 'in_review'
  const visibleSections = changesOnly ? changedSections : sections

  const treeRows: TreeRow[] = useMemo(() => {
    if (treeMode === 'diff') {
      return (compareDocs?.documents ?? []).map((d) => ({ id: d.documentId, name: d.name, diffType: d.diffType, changed: true }))
    }
    return (allDocs ?? []).map((d) => ({
      id: d.id, name: d.name,
      diffType: changedById.get(d.id)?.diffType ?? 'unchanged',
      changed: changedSet.has(d.id),
    }))
  }, [treeMode, compareDocs, allDocs, changedById, changedSet])
  const changedCount = changedSet.size
  const totalCount = allDocs?.length ?? changedCount

  function selectDoc(id: string) {
    setPickedDocId(id)
  }
  function decide(sectionKey: string, state: SectionReviewState) {
    setLocalReview((m) => ({ ...m, [sectionKey]: state }))
    if (activeDocId) reviewSection.mutate({ docId: activeDocId, sectionKey, reviewState: state })
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
        changedCount={changedCount} total={totalCount} loading={docsLoading}
      />

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {!activeDocId ? (
          /* ─── Empty state ─── */
          <div className="flex-1 flex items-center justify-center p-8 bg-surface-container-low overflow-y-auto">
            <div className="text-center max-w-[480px]">
              <div className="w-16 h-16 rounded-2xl bg-surface-container flex items-center justify-center mx-auto mb-5">
                <Icon name="difference" size={32} className="text-on-surface-variant" />
              </div>
              <h2 className="text-on-surface font-semibold text-lg mb-2">Select a document to compare</h2>
              <p className="text-on-surface-variant text-xs mb-1">
                Reference <span className="font-mono text-outline">{baselineShort}</span> → Current <span className="font-mono text-on-tertiary-container">{currentBranch} @ {currentShort}</span>
              </p>
              <p className="text-outline text-xs mb-8">Pick a document from the left panel, or a changed document below.</p>
              <div className="text-left space-y-2">
                {(compareDocs?.documents ?? []).map((d) => (
                  <button
                    key={d.documentId}
                    onClick={() => selectDoc(d.documentId)}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 bg-white border border-outline-variant rounded-lg hover:border-secondary transition-colors text-left"
                  >
                    <span className={cn('w-1.5 h-1.5 rounded-full flex-shrink-0', DIFF_BADGE[d.diffType].dot)} aria-hidden />
                    <span className="text-on-surface text-sm flex-1 truncate">{d.name}</span>
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
                    {reviewMode && (
                      <span className="flex items-center gap-0.5 px-1.5 py-0.5 rounded-lg text-label font-mono bg-[#fff8e6] text-[#b45309] border border-amber">
                        <Icon name="rate_review" size={10} />In Review
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
                {visibleSections.length === 0 ? (
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
                        <div className={cn('bg-white border-b border-outline-variant/60 px-8 py-6 transition-all', sectionAccent(s.diffType, s.reviewState))}>
                          <div className="flex items-start justify-between gap-3 mb-3">
                            <div className="flex items-baseline gap-2 min-w-0">
                              {s.number && <span className="font-mono text-caption text-outline flex-shrink-0">{s.number}</span>}
                              <h2 className={cn('text-primary font-semibold font-sans', headingSize)}>{s.title}</h2>
                            </div>
                            {changed && reviewMode && (
                              <SectionControls
                                review={s.reviewState}
                                onAccept={() => decide(s.key, 'accepted')}
                                onDecline={() => decide(s.key, 'declined')}
                              />
                            )}
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

            {/* Review footer — only while the doc is in review */}
            {reviewMode && (
              <footer className="flex-shrink-0 border-t border-outline-variant bg-white px-5 py-2.5 flex items-center justify-between min-h-11">
                <div className="flex items-center gap-3">
                  <div className="flex items-center gap-1" role="progressbar" aria-valuenow={resolved} aria-valuemax={total} aria-label={`${resolved} of ${total} changes resolved`}>
                    {changedSections.map((s) => (
                      <div key={s.key} className={cn('w-3 h-3 rounded-full transition-colors',
                        s.reviewState === 'accepted' ? 'bg-on-tertiary-container'
                          : s.reviewState === 'edited' ? 'bg-secondary'
                          : s.reviewState === 'declined' ? 'bg-error'
                          : 'bg-outline-variant')} />
                    ))}
                  </div>
                  <span className="text-on-surface-variant font-mono text-caption">{resolved}/{total} changes resolved</span>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => activeDocId && submitReview.mutate(activeDocId)}
                    className="flex items-center gap-1.5 px-3 py-1.5 border border-outline-variant rounded-lg hover:bg-surface-container-low transition-colors text-on-surface font-mono text-caption font-medium"
                  >
                    Submit Review
                  </button>
                  <button
                    onClick={() => activeDocId && approveDoc.mutate(activeDocId)}
                    disabled={total === 0 || resolved < total}
                    className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors disabled:opacity-50 font-mono text-caption font-bold tracking-[0.04em]"
                  >
                    <Icon name="check" size={14} />Approve Document
                  </button>
                </div>
              </footer>
            )}
          </>
        )}
      </div>
    </div>
  )
}
