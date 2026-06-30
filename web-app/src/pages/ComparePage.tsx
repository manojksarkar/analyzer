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
import type { DiffType, SectionReviewState } from '../types'

type TreeMode = 'diff' | 'all'

/* ─── Diff-type chip styling ─── */
const DIFF_BADGE: Record<DiffType, { label: string; cls: string; dot: string }> = {
  added:     { label: 'added',     cls: 'text-on-tertiary-container bg-[rgba(0,165,114,.1)]', dot: 'bg-on-tertiary-container' },
  changed:   { label: 'changed',   cls: 'text-secondary bg-secondary/10',                     dot: 'bg-secondary' },
  removed:   { label: 'removed',   cls: 'text-error bg-error-container',                       dot: 'bg-error' },
  unchanged: { label: 'unchanged', cls: 'text-on-surface-variant bg-surface-container',        dot: 'bg-outline-variant' },
}

/* ─── Section accent (left stripe at the gutter) by review state, else "changed" blue ─── */
function sectionAccent(diffType: DiffType, review: SectionReviewState | null): string {
  if (diffType === 'unchanged') return ''
  if (review === 'accepted') return 'border-l-[3px] border-l-on-tertiary-container bg-[rgba(0,165,114,.04)]'
  if (review === 'declined') return 'border-l-[3px] border-l-outline-variant bg-surface-container-low'
  if (review === 'edited')   return 'border-l-[3px] border-l-secondary bg-[rgba(0,88,190,.04)]'
  return 'border-l-[3px] border-l-secondary bg-surface-container-low'
}

/* ─── Markdown body → richtext / table blocks ─── */
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
function SectionControls({ review, onAccept, onDecline, onEdit }: {
  review: SectionReviewState | null
  onAccept: () => void; onDecline: () => void; onEdit: () => void
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
      <button onClick={onEdit} className="flex items-center gap-1 px-2 py-0.5 rounded border border-outline-variant hover:bg-surface-container text-on-surface-variant transition-colors text-label font-mono">
        <Icon name="edit" size={11} />Edit
      </button>
    </div>
  )
}

interface MergedSection {
  key: string
  title: string
  diffType: DiffType
  current: string
  baseline: string
  reviewState: SectionReviewState | null
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
  const [editing, setEditing] = useState<{ key: string; title: string; content: string } | null>(null)

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

  /* Compare detail (diff_type + baseline) overlaid with the live doc detail
     (edited content + persisted review_state). */
  const liveByKey = useMemo(() => new Map((docDetail?.sections ?? []).map((s) => [s.key, s])), [docDetail])
  const sections: MergedSection[] = useMemo(
    () => (detail?.sections ?? []).map((s) => {
      const live = liveByKey.get(s.key)
      return {
        key: s.key,
        title: s.title,
        diffType: s.diffType,
        current: live?.content ?? s.currentContent,
        baseline: s.baselineContent,
        reviewState: live?.reviewState ?? null,
      }
    }),
    [detail, liveByKey],
  )

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
    setEditing(null)
  }
  function decide(sectionKey: string, state: SectionReviewState) {
    if (activeDocId) reviewSection.mutate({ docId: activeDocId, sectionKey, reviewState: state })
  }
  function saveEdit() {
    if (activeDocId && editing) {
      reviewSection.mutate({ docId: activeDocId, sectionKey: editing.key, reviewState: 'edited', editedContent: editing.content })
    }
    setEditing(null)
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
                    return (
                      <Fragment key={s.key}>
                        {/* Reference cell */}
                        <div className={cn('bg-white border-r border-b border-outline-variant/60 px-8 py-6', changed && 'opacity-70')}>
                          <h2 className="text-primary font-semibold mb-3 font-sans text-lg">{s.title}</h2>
                          <SectionBody content={s.baseline} />
                        </div>
                        {/* Current cell */}
                        <div className={cn('bg-white border-b border-outline-variant/60 px-8 py-6 transition-all', sectionAccent(s.diffType, s.reviewState))}>
                          <div className="flex items-start justify-between gap-3 mb-3">
                            <h2 className="text-primary font-semibold font-sans text-lg">{s.title}</h2>
                            {changed && reviewMode && (
                              <SectionControls
                                review={s.reviewState}
                                onAccept={() => decide(s.key, 'accepted')}
                                onDecline={() => decide(s.key, 'declined')}
                                onEdit={() => setEditing({ key: s.key, title: s.title, content: s.current })}
                              />
                            )}
                          </div>
                          <SectionBody content={s.current} />
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

      {/* Edit modal */}
      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-6 bg-[rgba(4,22,39,.4)]">
          <div className="bg-white rounded-xl w-full max-w-[560px] overflow-hidden shadow-[0_8px_40px_rgba(4,22,39,.2)]">
            <div className="px-6 py-4 border-b border-outline-variant flex items-center justify-between">
              <h3 className="text-on-surface font-semibold text-lg">Edit {editing.title}</h3>
              <button onClick={() => setEditing(null)} className="p-1 hover:bg-surface-container rounded-lg transition-colors">
                <Icon name="close" size={20} className="text-on-surface-variant" />
              </button>
            </div>
            <div className="p-6">
              <p className="text-on-surface-variant text-xs mb-3">Edit the content for this section. Changes are saved and the section is marked "Edited".</p>
              <textarea
                rows={8}
                value={editing.content}
                onChange={(e) => setEditing({ ...editing, content: e.target.value })}
                className="w-full border border-outline-variant rounded-lg px-3 py-2.5 text-sm text-on-surface focus:outline-none focus:ring-2 focus:ring-secondary/30 resize-none font-mono"
              />
            </div>
            <div className="px-6 py-4 border-t border-outline-variant flex items-center justify-end gap-2">
              <button onClick={() => setEditing(null)} className="px-4 py-2 border border-outline-variant hover:bg-surface-container rounded-lg font-mono text-caption text-on-surface-variant transition-colors">Cancel</button>
              <button onClick={saveEdit} className="px-4 py-2 bg-secondary hover:bg-secondary-container text-white rounded-lg font-mono text-caption transition-colors flex items-center gap-1.5">
                <Icon name="save" size={14} />Save &amp; Accept
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
