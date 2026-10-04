import { useState, useMemo, Fragment } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import {
  useVersions, useCommits, useDocuments, useDocument,
} from '../../hooks/useProjects'
import { useProjectViewState } from '../../hooks/useProjectViewState'
import { useCompareDocuments, useCompareDocumentDetail } from '../../hooks/useCompare'
import { Icon, Skeleton, CompareSectionSkeleton, StatusBadge } from '../../components/ui'
import { LoadError } from '../../components/LoadError'
import { cn } from '../../lib/cn'
import { documentSubtitle } from '../../lib/docTree'
import { failedLoad } from '../../lib/failedLoad'
import { BlocksPane, SectionBody } from './components/DiffBlocks'
import { DocTree, type TreeRow } from './components/DocTree'
import { DocStateBar } from './components/DocStateBar'
import { ReferencePicker } from './components/ReferencePicker'
import {
  DIFF_BADGE, compareVersions, olderVersions, paneSections, sectionAccent, versionRef, type TreeMode,
} from './helpers'

export function ComparePage() {
  const { projectId } = useParams<{ projectId: string }>()
  const pid = projectId ?? ''
  const [searchParams, setSearchParams] = useSearchParams()
  // The page's address carries what is open: `?doc=` the document (a link from the documents
  // list opens on it), `?ref=` a reference other than the default.
  const setParam = (key: string, value: string) =>
    setSearchParams((p) => { p.set(key, value); return p }, { replace: true })

  const versionsQuery = useVersions(pid)
  const { data: versions } = versionsQuery
  const { data: commits } = useCommits(pid)
  const { viewVersion, isLoading: viewLoading } = useProjectViewState(pid)

  /* Current = the Subbar picker's version (defaults to the latest); the reference is the version
     before it, or an older one picked here. Both by version id, end to end: two versions of one
     commit are two versions (by commit, the second found the first, and showed "No changes"). */
  const { current: currentVersion, baseline: baselineVersion } =
    compareVersions(versions, viewVersion, searchParams.get('ref'))
  const referenceOptions = olderVersions(versions, currentVersion)
  const currentRef = versionRef(currentVersion)
  const baselineRef = versionRef(baselineVersion)
  const currentCommit = commits?.find((c) => c.sha === currentVersion?.sha)
  const baselineCommit = commits?.find((c) => c.sha === baselineVersion?.sha)

  const [treeModePick, setTreeMode] = useState<TreeMode | null>(null)
  const [changesOnly, setChangesOnly] = useState(false)

  const compareDocsQuery = useCompareDocuments(pid, currentRef, baselineRef)
  const { data: compareDocs, isLoading: docsLoading } = compareDocsQuery
  const allDocsQuery = useDocuments(pid, currentVersion?.id ? { versionId: currentVersion.id } : undefined)
  const { data: allDocs, isLoading: allDocsLoading } = allDocsQuery

  const changedSet = useMemo(() => new Set((compareDocs?.documents ?? []).map((d) => d.documentId)), [compareDocs])
  const changedById = useMemo(() => new Map((compareDocs?.documents ?? []).map((d) => [d.documentId, d])), [compareDocs])
  // Each current document's review state, shown beside it (never changed here).
  const docById = useMemo(() => new Map((allDocs ?? []).map((d) => [d.id, d])), [allDocs])

  /* Active doc = the one `?doc=` names (a pick sets it) when it is a document of either version,
     changed or not, else the first changed one. An unchanged one opens too, under "All": the
     list's Compare named it, and the page opened the first changed document instead. */
  const paramDoc = searchParams.get('doc')
  const paramChanged = !!paramDoc && changedSet.has(paramDoc)
  const paramKnown = paramChanged || (!!paramDoc && docById.has(paramDoc))
  // Until the current version's documents are read, an unchanged one is not known yet.
  const paramPending = !!paramDoc && !paramKnown && allDocsLoading
  const activeDocId = (paramKnown ? paramDoc : null) ?? compareDocs?.documents?.[0]?.documentId ?? null
  const treeMode: TreeMode = treeModePick ?? (paramKnown && !paramChanged ? 'all' : 'diff')

  const detailQuery = useCompareDocumentDetail(pid, activeDocId ?? undefined, currentRef, baselineRef)
  const { data: detail, isLoading: detailLoading } = detailQuery
  // The open document's review state, shown under it (read-only here). Only for a document of
  // the Current side: a removed one is the reference's.
  const { data: docDetail } = useDocument(pid, activeDocId ?? '')
  const stateDoc = docDetail && currentVersion?.id && docDetail.versionId === currentVersion.id ? docDetail : undefined

  const isRich = detail?.mode === 'rich'
  const sections = useMemo(() => paneSections(detail), [detail])

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

  // A failed read is shown as one, with Retry — never as "Nothing to compare" or "No changes".
  const pageFailed = failedLoad(versionsQuery, compareDocsQuery)
  const treeFailed = treeMode === 'all' ? failedLoad(allDocsQuery) : null
  const detailFailed = failedLoad(detailQuery)

  function selectDoc(id: string) {
    setParam('doc', id)
  }

  const docTitle = detail?.documentName ?? docDetail?.name ?? changedById.get(activeDocId ?? '')?.name ?? 'Document'
  // The document's own title line (SWE.3 or SWE.4), not always SWE.3's.
  const docSubtitle = documentSubtitle({
    process: docDetail?.process ?? changedById.get(activeDocId ?? '')?.process,
    subtitle: docDetail?.subtitle,
  })
  const currentTag = currentVersion?.tag ?? currentCommit?.versionTag
  const currentBranch = currentCommit?.branch ?? currentVersion?.branch ?? 'main'
  const currentShort = currentCommit?.shortSha ?? currentVersion?.shortSha ?? '—'
  const baselineShort = baselineCommit?.shortSha ?? baselineVersion?.shortSha ?? '—'
  const isLatest = !!currentVersion && versionRef(versions?.[0]) === currentRef

  if (pageFailed) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <LoadError what="the comparison" error={pageFailed.error} retrying={pageFailed.retrying} onRetry={pageFailed.retry} />
      </div>
    )
  }

  return (
    <div className="flex h-full overflow-hidden">
      <DocTree
        rows={treeRows} mode={treeMode} setMode={setTreeMode}
        activeId={activeDocId} onSelect={selectDoc}
        changedCount={changedCount} total={totalCount}
        loading={treeMode === 'diff' ? docsLoading && !compareDocs : (allDocsLoading || versionsQuery.isLoading) && !allDocs}
        failed={treeFailed}
      />

      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Loading until the versions say what is compared and the list (and a linked document)
            is read: it said "Nothing to compare yet" while the versions loaded. */}
        {(viewLoading && !versions) || (docsLoading && !compareDocs) || paramPending ? (
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
              <p className="text-on-surface-variant text-xs mb-1 flex items-center justify-center gap-1 flex-wrap">
                Reference <ReferencePicker options={referenceOptions} value={baselineVersion} fallback={baselineShort} onPick={(r) => setParam('ref', r)} /> → Current <span className="font-mono text-on-tertiary-container">{currentTag ?? `${currentBranch} @ ${currentShort}`}</span>
              </p>
              <p className="text-outline text-xs mb-8">
                {!currentVersion ? 'This commit has no version yet. Pick a version in the bar above, or run analysis on this commit.'
                  : !baselineRef ? 'This is the project’s first version: there is no version before it to compare with.'
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
                    <span className={cn('px-1.5 py-0.5 rounded font-mono text-caption', DIFF_BADGE[d.diffType].cls)}>{DIFF_BADGE[d.diffType].sign} {DIFF_BADGE[d.diffType].label}</span>
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
                  <ReferencePicker options={referenceOptions} value={baselineVersion} fallback={baselineShort} onPick={(r) => setParam('ref', r)} />
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
                  <p className="text-on-surface-variant mt-0.5 text-xs">{docSubtitle}</p>
                </div>
                <div className="bg-white border-b border-outline-variant/60 px-8 pt-7 pb-5">
                  <p className="text-on-surface-variant uppercase mb-1 font-mono text-caption tracking-[0.1em]">{currentShort}</p>
                  <h1 className="text-primary font-semibold font-sans text-2xl">{docTitle}</h1>
                  <p className="text-on-surface-variant mt-0.5 text-xs">{docSubtitle}</p>
                </div>

                {/* Per-section rows — grid auto-row height = the taller side, so the
                    two cells of a row start at the same Y (filler on the shorter one). */}
                {detailFailed ? (
                  <div className="col-span-2 bg-white px-8 py-6">
                    <LoadError compact what="this document's changes" error={detailFailed.error}
                               retrying={detailFailed.retrying} onRetry={detailFailed.retry} />
                  </div>
                ) : detailLoading && sections.length === 0 ? (
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
                              <span className={cn('px-1.5 py-0.5 rounded font-mono text-caption', DIFF_BADGE[s.diffType].cls)}>{DIFF_BADGE[s.diffType].sign} {DIFF_BADGE[s.diffType].label}</span>
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
