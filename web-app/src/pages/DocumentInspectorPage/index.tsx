import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useIsFetching, useIsMutating } from '@tanstack/react-query'
import {
  projectKeys, useDocument, useDocuments, useDocumentRender, useTeam, useProject,
} from '../../hooks/useProjects'
import { useFollowDocumentVersion, useProjectViewState } from '../../hooks/useProjectViewState'
import { useDownloadDoc } from '../../hooks/useDocumentMutations'
import { useDocumentEvents, useDocumentReadiness } from '../../hooks/useApproval'
import {
  correctionSaveKey, useDiscardOrphans, useExportReadiness, useSaveSlot, useUndoSlot, useVersionOverrides,
} from '../../hooks/useReview'
import { useJustUpdated, useWordFilesWatcher } from '../../hooks/useWordFiles'
import { useAuthStore } from '../../store/auth'
import { useUIStore } from '../../store/ui'
import { DocTreePanel } from '../../components/shell/DocTreePanel'
import { SubbarCta } from '../../components/shell/SubbarCta'
import { AssignReviewerDialog } from '../../components/review/AssignReviewerDialog'
import { UpdateWordFilesDialog } from '../../components/wordfiles/UpdateWordFilesDialog'
import { WordFileMenu } from '../../components/wordfiles/WordFileMenu'
import {
  groupDocsByProcess, buildReviewerOptions, docxFileName, documentSubtitle, matchesReviewer,
} from '../../lib/docTree'
import { componentWordFileStale } from '../../lib/reviewStatus'
import {
  cap, componentNamer, editHold, isUpdating, outOfDateFiles, outOfDateWhy, readerBanner,
  retryOf, updateBlocked,
  type FailedUpdate, type UpdateAsk, type Wording,
} from '../../lib/wordFiles'
import { Card, Icon, Skeleton, Text, toast } from '../../components/ui'
import { LoadError } from '../../components/LoadError'
import { cn } from '../../lib/cn'
import { isNotFound } from '../../lib/http'
import type { FlowchartEntry, Slot } from '../../types'
import { Swe4Body, Swe4Strip } from './components/Swe4Reader'
import { RichSectionView } from './components/Sections'
import { MetaBanner } from './components/MetaBanner'
import { ReviewTab } from './components/ReviewTab'
import { ApproveDialog, ReopenDialog, RequestChangesDialog } from './components/ReviewDialogs'
import { RightPanel, type PanelTab } from './components/RightPanel'
import { OutlineTab } from './components/OutlineTab'
import { CorrectionsTab } from './components/CorrectionsTab'
import { QueuedList } from './components/QueuedList'
import { EditBar, ReviewStateBanner, type EditHold } from './components/ReviewBars'
import { WordFileBanner } from './components/WordFileBanner'
import { FlowchartLabelDialog } from './components/FlowchartLabelDialog'
import { TreeRail } from './components/TreeRail'
import { EditContext, type EditApi } from './editContext'
import {
  buildOutline, docCorrections, docSlots, outlineIds, slotRef, undoneInWordFile, unitCorrectionCounts,
} from './outline'
import { isMine, type ReviewCtx } from './review'
import { useScrollSpy } from './useScrollSpy'

type ReviewDialog = 'assign' | 'approve' | 'changes' | 'reopen'

/** Bring a text into view and flash it, so the eye finds it. */
function reveal(el: Element | null | undefined) {
  if (!el) return
  el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  el.animate?.([{ backgroundColor: '#fde68a' }, { backgroundColor: 'transparent' }], { duration: 1800 })
}

export function DocumentInspectorPage() {
  const { projectId, docId } = useParams<{ projectId: string; docId: string }>()
  const pid = projectId ?? ''
  const navigate = useNavigate()

  const { data: project } = useProject(pid)
  const docQuery = useDocument(pid, docId ?? '')
  const { data: doc, isLoading } = docQuery
  const renderQuery = useDocumentRender(pid, docId ?? '')
  const { data: rich } = renderQuery
  const { data: team } = useTeam(pid)
  const { viewVersion, pageState } = useProjectViewState(pid)
  // Opened on this document (a link, a notification, an address): the Subbar's version chip and
  // status are its version's, not the latest's.
  useFollowDocumentVersion(pid, doc)
  // The left rail lists every doc of THIS document's version, so you can jump between documents
  // without going back. Not the Subbar's: while a newer run is going, the Subbar shows that
  // run's draft, which has no documents, and the rail said "No documents" beside an open one.
  const railVersionId = doc?.versionId ?? viewVersion?.id
  const { data: railDocs, isLoading: railLoading } = useDocuments(pid, railVersionId ? { versionId: railVersionId } : undefined)
  const versionId = doc?.versionId ?? ''

  const downloadDoc = useDownloadDoc(pid)
  const { data: readiness, isError: readinessFailed } = useExportReadiness(pid, versionId || undefined)
  // Review and approval: R9 for this document alone (the Approve guard), and its record.
  const { data: docReadiness, isError: docReadinessFailed } = useDocumentReadiness(pid, versionId || undefined, doc?.id)
  const { data: events } = useDocumentEvents(pid, doc?.id)
  // `mutateAsync`/`mutate` are stable across renders; the mutation objects are not, and the edit
  // context below must not change on every job poll (it would re-render every correctable text).
  const { mutateAsync: saveText } = useSaveSlot(pid, versionId)
  const { mutate: undoText } = useUndoSlot(pid, versionId)
  const discardOrphans = useDiscardOrphans(pid, versionId)

  const isAdmin = project?.userRole === 'admin'
  const isDeveloper = project?.userRole === 'developer'
  const meId = useAuthStore((s) => s.user?.id ?? '')
  const panelCollapsed = useUIStore((s) => s.inspectorPanelCollapsed)
  const togglePanel = useUIStore((s) => s.toggleInspectorPanel)
  const treeFolded = useUIStore((s) => s.docTreeFolded)
  const setTreeFolded = useUIStore((s) => s.setDocTreeFolded)

  const [canvasEl, setCanvasEl] = useState<HTMLElement | null>(null)
  const [dialog, setDialog] = useState<ReviewDialog | null>(null)
  const [assigneeFilter, setAssigneeFilter] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [openChart, setOpenChart] = useState<FlowchartEntry | null>(null)
  // `?tab=review` (from the list's Review action, or a notification) opens the Review tab; a
  // click on a tab takes over from it.
  const [searchParams, setSearchParams] = useSearchParams()
  const urlTab = searchParams.get('tab')
  const [tabState, setTabState] = useState('outline')
  const tab = urlTab ?? tabState
  function setTab(t: string) {
    setTabState(t)
    if (urlTab) setSearchParams((p) => { p.delete('tab'); return p }, { replace: true })
  }

  const isSwe4 = doc?.process === 'SWE.4'
  const sections = useMemo(() => rich?.sections ?? [], [rich])
  const slots = useMemo(() => (isSwe4 ? [] : docSlots(sections)), [sections, isSwe4])
  const canEdit = !isSwe4 && slots.length > 0 && !!versionId
  const { data: overrides, isLoading: overridesLoading, isError: overridesError } =
    useVersionOverrides(pid, canEdit ? versionId : undefined)
  const corrections = useMemo(
    () => docCorrections(overrides ?? [], sections, rich?.cover.group ?? ''), [overrides, sections, rich])
  const counts = useMemo(() => unitCorrectionCounts(corrections.inForce, sections), [corrections, sections])
  const slotRefs = useMemo(() => new Set(slots.map((s) => slotRef(s.kind, s.key))), [slots])
  // The outline stops at units for SWE.4 (as the mockup): a line per test spec would bury it.
  const outline = useMemo(() => buildOutline(sections, isSwe4 ? 3 : 4), [sections, isSwe4])
  const ids = useMemo(() => outlineIds(outline), [outline])
  const activeId = useScrollSpy(canvasEl, ids)

  const names = useMemo(() => new Map((team ?? []).map((m) => [m.userId ?? m.id, m.name])), [team])
  const userName = useCallback((id: string | null) => (id ? names.get(id) ?? '' : ''), [names])
  const nameOf = useCallback((id: string) => names.get(id), [names])

  // Word files (WORD_FILE_UPDATES): the version's tag and its components' names for what the
  // screens say; the end of an update said once for the page; what an update just wrote.
  const versionTag = rich?.cover.version ?? doc?.version ?? ''
  const outOfDateNamed = readiness?.outOfDate
  const words: Wording = useMemo(
    () => ({ versionTag, nameOf: componentNamer(railDocs ?? [], outOfDateNamed ?? []) }),
    [versionTag, railDocs, outOfDateNamed])
  useWordFilesWatcher(pid, versionId, readiness, { meId, words })
  const justUpdated = useJustUpdated(versionId || undefined)
  const [ask, setAsk] = useState<UpdateAsk | null>(null)
  /** Every update a button starts on its own asks first; while nothing can start, it says why. */
  const askUpdate = useCallback((a: UpdateAsk) => {
    const why = updateBlocked(readiness, a.rebuild ? null : a.components, words, !!a.rebuild)
    if (why) toast.info(why)
    else setAsk(a)
  }, [readiness, words])

  // Done editing: when this Word file is out of date, say so with the way to update it — a
  // suggestion, never an update started on its own (WORD_FILE_UPDATES D7). Said once the saves
  // the Done click set off (the box's blur) have settled and R9 has been read again: before, R9
  // would not have the last correction yet.
  const suggestWanted = useRef(false)
  const saving = useIsMutating({ mutationKey: correctionSaveKey(pid, versionId) })
  const checking = useIsFetching({ queryKey: projectKeys.exportReadiness(pid, versionId) })
  useEffect(() => {
    if (!suggestWanted.current || saving > 0 || checking > 0 || !doc) return
    suggestWanted.current = false
    const stale = doc.status !== 'approved'
      && outOfDateFiles(readiness, railDocs ?? []).some((f) => f.documentId === doc.id)
    if (!stale || isUpdating(readiness, doc)) return
    const group = doc.group ?? ''
    const why = updateBlocked(readiness, [group], words)
    toast.info('Word file out of date.', why || undefined,
      why ? undefined : { label: 'Update', onClick: () => askUpdate({ components: [group] }) })
  })
  // Corrections wait while an update writes this document's component (409 WORD_FILE_UPDATING);
  // every other document stays editable. A run rebuilding the version pauses editing too.
  const hold: EditHold = (doc && (editHold(readiness, doc) ?? editHold(docReadiness, doc)))
    ?? (pageState === 'running' ? 'run' : null)
  const locked = hold !== null
  // Approved: locked. No corrections, so no edit mode, until an admin reopens it.
  const approved = doc?.status === 'approved'
  const isEditing = editing && canEdit && !approved
  // A flowchart's labels are SWE.4's test steps too: they lock while the component's SWE.4 is
  // approved (the server refuses a label save with 409 DOCUMENT_APPROVED).
  const swe4Approved = !isSwe4 && !!doc && (railDocs ?? []).some(
    (d) => d.process === 'SWE.4' && d.group === doc.group && d.status === 'approved')
  const labelsLocked = swe4Approved && doc
    ? `SWE.4 of ${doc.name} is approved, and its test steps are built from these labels. An admin can reopen it.`
    : null
  const editApi: EditApi = useMemo(() => ({
    editing: isEditing,
    locked,
    projectId: pid,
    versionId,
    save: (slot: Slot, text: string) => saveText({ slot, text }),
    undo: (slot: Slot) => undoText(slot),
    openFlowchart: (chart: FlowchartEntry) => {
      if (labelsLocked) toast.info('These labels are locked.', labelsLocked)
      else setOpenChart(chart)
    },
    labelsLocked,
    userName,
  }), [isEditing, locked, pid, versionId, saveText, undoText, labelsLocked, userName])

  function jumpToSection(id: string) {
    document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  function jumpToSlot(slot: Slot) {
    const all = Array.from(document.querySelectorAll<HTMLElement>('[data-slot-key], [data-flowchart-id]'))
    reveal(slot.kind === 'nodeLabel'
      ? all.find((el) => el.dataset.flowchartId === slot.flowchartId)
      : all.find((el) => el.dataset.slotKey === slot.key))
  }

  // Rail data (reviewer filter shared with the dropdown, mirrors DocumentsPage).
  const allRailDocs = railDocs ?? []
  const railAssignee = assigneeFilter ?? (isDeveloper ? meId : '')
  const railGroups = groupDocsByProcess(allRailDocs.filter((d) => matchesReviewer(d, railAssignee)))
  const railAssignees = buildReviewerOptions(allRailDocs)

  if (isLoading) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="max-w-3xl mx-auto px-6 py-8 space-y-4">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  // A failed read is not "not found": say what failed, and offer Retry. Only the API's 404 is.
  if (!doc && docQuery.isError && !isNotFound(docQuery.error)) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="p-6">
          <Card>
            <LoadError what="the document" error={docQuery.error} retrying={docQuery.isFetching}
                       onRetry={() => { void docQuery.refetch() }} />
          </Card>
        </div>
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="p-6">
          <Card className="py-20 flex flex-col items-center text-center gap-4">
            <Icon name="error_outline" size={32} className="text-on-surface-variant" />
            <div>
              <Text as="p" variant="heading" className="text-on-surface">Document not found</Text>
              <Text as="p" variant="caption" className="font-mono mt-1">It may have been removed or never generated.</Text>
            </div>
            <button
              onClick={() => navigate(`/projects/${pid}/documents`)}
              className="flex items-center gap-1.5 px-4 py-2 border border-outline-variant rounded-lg hover:bg-surface-container transition-colors font-mono text-caption text-on-surface-variant"
            >
              <Icon name="arrow_back" size={15} />
              Back to documents
            </button>
          </Card>
        </div>
      </div>
    )
  }

  // An approval carried from an earlier version means the content is the same: nothing to compare.
  const isUnchanged = !!doc.review.carriedFrom
  // The document's own version (its cover says the same), not the Subbar's pick.
  const refLabel = rich?.cover.version ?? doc.version
  // An approved document downloads the Word file that was approved (a copy is kept), so a later
  // correction elsewhere in the version does not make it out of date. Otherwise: out of date when
  // R9 lists it (`outOfDate`, WORD_FILE_UPDATES §4.3).
  const wordStale = componentWordFileStale(readiness, doc.group)
  const files = outOfDateFiles(readiness, allRailDocs)
  const own = approved ? undefined : files.find((f) => f.documentId === doc.id)
  const docStale = !!own
  // Undone corrections the Word file may still carry: every one, while it is stale (R9 counts them).
  const undoneShown = undoneInWordFile(corrections.undone, wordStale)
  const versionOrphans = (overrides ?? []).filter((s) => s.isOrphaned).length
  const reviewCtx: ReviewCtx = { isAdmin: !!isAdmin, meId }
  const changesEvent = events?.find((e) => e.kind === 'changes_requested')
  const docCorrectionCount = isSwe4 || !canEdit ? null : corrections.inForce.length
  function openReview() {
    setTab('review')
    if (panelCollapsed) togglePanel()
  }

  /* ── Word files: every update a button starts on its own asks first (the confirm dialog); while
     nothing can start, the button says why instead. ── */
  const fileName = docxFileName(doc)
  const group = doc.group ?? ''
  const myDocIds = allRailDocs.filter((d) => !!meId && d.reviewer?.userId === meId).map((d) => d.id)
  const banner = readerBanner({
    readiness, readinessFailed, doc, docs: allRailDocs, isAdmin: !!isAdmin, meId, myDocIds, justUpdated, words,
  })
  const dlBlocked = docStale ? updateBlocked(readiness, [group], words) : ''
  // Try again from the Review tab: here when this role's update reaches the failed components (the
  // components of the documents they review, plus this one), else from the document that does.
  const reviewedGroups = [...new Set(allRailDocs.filter((d) => myDocIds.includes(d.id)).map((d) => d.group ?? '').filter(Boolean))]
  const retryFor = (f: FailedUpdate) =>
    retryOf(f, { isAdmin: !!isAdmin, reviewed: reviewedGroups, openGroup: doc.group, docs: allRailDocs })

  const tabs: PanelTab[] = [
    { id: 'outline', label: 'Outline' },
    { id: 'review', label: 'Review' },
    ...(canEdit ? [{ id: 'corr', label: 'Corrections', count: corrections.inForce.length + undoneShown.length }] : []),
  ]
  const activeTab = tabs.some((t) => t.id === tab) ? tab : 'outline'

  return (
    <EditContext.Provider value={editApi}>
    <div className="flex-1 flex overflow-hidden min-h-0 relative">

      {/* ── Edit / Done (review & update): SWE.3 only; SWE.4 follows its flowchart labels ── */}
      {canEdit && (
        <SubbarCta>
          <button
            onClick={() => {
              // Done: the suggestion waits for the box's save and R9's next read (the effect above).
              if (isEditing) suggestWanted.current = true
              setEditing((v) => !v)
            }}
            aria-pressed={isEditing}
            disabled={approved}
            title={approved ? 'Approved: locked. An admin can reopen it.' : undefined}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em] border disabled:opacity-45 disabled:cursor-not-allowed',
              isEditing ? 'bg-secondary border-secondary text-on-secondary hover:bg-secondary-container' : 'border-secondary text-secondary bg-white hover:bg-surface-container-low',
            )}
          >
            <Icon name={approved ? 'lock' : isEditing ? 'check' : 'edit'} size={14} />
            {isEditing ? 'DONE' : 'EDIT'}
          </button>
        </SubbarCta>
      )}

      {/* ── Left document list: folds to a rail, as the reader needs the width ── */}
      {treeFolded ? <TreeRail onOpen={() => setTreeFolded(false)} /> : (
        <DocTreePanel
          groups={railGroups}
          assigneeOptions={railAssignees}
          effectiveAssignee={railAssignee}
          meId={meId}
          isDeveloper={!!isDeveloper}
          activeDocId={doc.id}
          onPickAssignee={setAssigneeFilter}
          onOpenDoc={(d) => navigate(`/projects/${pid}/documents/${d.id}`)}
          onFold={() => setTreeFolded(true)}
          loading={railLoading}
        />
      )}

      {/* ── Document canvas ── */}
      <main ref={setCanvasEl} className="flex-1 overflow-y-auto bg-surface-container-low">
        {isEditing && <EditBar hold={hold} />}
        {/* The reading column: room for the tables at a laptop's width (paddings grow on a wide
            screen only), capped so a wide screen does not stretch the lines; prose keeps its own
            measure (Sections). */}
        <div className="max-w-[1120px] mx-auto px-4 py-6 2xl:px-6 2xl:py-8">
          <ReviewStateBanner
            doc={doc}
            isAdmin={!!isAdmin}
            isMine={isMine(doc, { meId })}
            changesBy={changesEvent?.actor?.name}
            changesAt={changesEvent?.at}
            versionTag={refLabel}
            onReopen={() => setDialog('reopen')}
            onOpenReview={openReview}
          />
          {versionId && (
            <WordFileBanner
              projectId={pid}
              state={banner}
              isAdmin={!!isAdmin}
              rebuildBlocked={updateBlocked(readiness, null, words, true)}
              failedRenders={readiness?.failedRenders ?? 0}
              onAsk={askUpdate}
              onDownload={() => downloadDoc(doc.id, fileName)}
            />
          )}
          <div className="bg-white rounded-xl border border-outline-variant overflow-hidden shadow-[0_1px_4px_rgba(4,22,39,.06)]">

            {/* Cover header */}
            <div className="px-5 pt-8 pb-6 2xl:px-8 2xl:pt-10 2xl:pb-8 border-b border-outline-variant">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <Text as="p" variant="label" className="text-on-surface-variant tracking-[0.1em] mb-2">
                    {(rich?.cover.process ?? doc.process)} · <span className="font-mono">{rich?.cover.version ?? refLabel}</span>
                  </Text>
                  <h1 className="text-[28px] font-bold leading-tight tracking-[-0.02em] text-on-surface">{doc.name}</h1>
                  <p className="text-sm text-on-surface-variant mt-1">{rich?.cover.subtitle ?? documentSubtitle(doc)}</p>
                  {rich && (
                    <div className="flex flex-wrap items-center gap-1.5 mt-3">
                      {[rich.cover.projectName, rich.cover.layer, rich.cover.group, rich.cover.standard]
                        .filter(Boolean)
                        .map((t, i) => (
                          <span key={i} className="font-mono text-label text-on-surface-variant bg-surface-container-low border border-outline-variant rounded px-1.5 py-0.5">{t}</span>
                        ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  {/* Out of date: a small menu — the corrected file (updated first, after the
                      confirm) or the current file as it is. Otherwise a plain download. */}
                  {own ? (
                    <WordFileMenu
                      label="Download"
                      trigger={(
                        <button
                          type="button"
                          title={`Out of date: ${outOfDateWhy(own)}`}
                          className="relative flex items-center gap-1.5 px-3 py-2 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors font-mono text-caption font-medium"
                        >
                          <Icon name="download" size={15} />
                          DOCX
                          <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-amber border-2 border-white" aria-hidden />
                          <span className="sr-only"> (out of date)</span>
                        </button>
                      )}
                      items={[
                        {
                          icon: 'sync', label: 'Corrected file', sub: dlBlocked || 'Updated first', disabled: !!dlBlocked,
                          onSelect: () => askUpdate({ components: [group], download: { docId: doc.id, fileName } }),
                        },
                        {
                          icon: 'download', label: 'Current file', sub: cap(outOfDateWhy(own)),
                          onSelect: () => { void downloadDoc(doc.id, fileName) },
                        },
                      ]}
                    />
                  ) : (
                    <button
                      onClick={() => downloadDoc(doc.id, fileName)}
                      className="relative flex items-center gap-1.5 px-3 py-2 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors font-mono text-caption font-medium"
                    >
                      <Icon name="download" size={15} />
                      DOCX
                    </button>
                  )}
                  {!isUnchanged && (
                    <button
                      onClick={() => navigate(`/projects/${pid}/compare?doc=${doc.id}`)}
                      title="Compare vs reference"
                      className="flex items-center gap-1.5 px-3 py-2 border border-outline-variant hover:border-secondary hover:text-secondary text-on-surface-variant rounded-lg transition-colors font-mono text-caption font-medium"
                    >
                      <Icon name="compare_arrows" size={15} />
                      Compare
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Meta banner — pipeline/model availability + counts (SWE.4: its test counts) */}
            {rich && (isSwe4 && rich.testSummary ? <Swe4Strip summary={rich.testSummary} /> : <MetaBanner meta={rich.meta} />)}

            {/* Sections */}
            {rich && isSwe4 ? <Swe4Body sections={rich.sections} /> : (
            <div className="px-5 py-8 space-y-10 2xl:px-8 2xl:py-10 2xl:space-y-12">
              {!rich && renderQuery.isError ? (
                <LoadError compact what="the document's content" error={renderQuery.error}
                           retrying={renderQuery.isFetching} onRetry={() => { void renderQuery.refetch() }} />
              ) : !rich ? (
                <div className="space-y-4">
                  <Skeleton className="h-6 w-1/3" />
                  <Skeleton className="h-24" />
                  <Skeleton className="h-24" />
                </div>
              ) : rich.sections.length === 0 ? (
                <div className="bg-surface-container-low border border-outline-variant rounded-lg flex flex-col items-center text-center py-14 gap-3">
                  <Icon name="description" size={40} className="text-outline-variant" />
                  <Text as="p" variant="caption" className="font-mono">No section content for this document yet.</Text>
                </div>
              ) : (
                rich.sections.map((s) => <RichSectionView key={s.id} section={s} />)
              )}
            </div>
            )}
          </div>
        </div>
      </main>

      {/* ── Right panel: Outline · Review · Corrections ── */}
      <RightPanel tabs={tabs} active={activeTab} onTab={setTab} collapsed={panelCollapsed} onToggle={togglePanel}>
        {activeTab === 'review' ? (
          <ReviewTab
            key={doc.id}
            projectId={pid}
            doc={doc}
            versionTag={refLabel}
            ctx={reviewCtx}
            readiness={docReadiness}
            readinessFailed={docReadinessFailed}
            corrections={docCorrectionCount}
            isSwe3={!isSwe4}
            nameOf={nameOf}
            words={words}
            onAssign={() => setDialog('assign')}
            onApprove={() => setDialog('approve')}
            onChanges={() => setDialog('changes')}
            onReopen={() => setDialog('reopen')}
            onSubmitted={() => setEditing(false)}
            onUpdate={askUpdate}
            retryFor={retryFor}
          />
        ) : activeTab === 'corr' ? (
          <CorrectionsTab
            inForce={corrections.inForce}
            undone={undoneShown}
            orphans={corrections.orphans}
            isLoading={overridesLoading}
            isError={overridesError}
            userName={userName}
            onJump={jumpToSlot}
            orphanActions={isAdmin ? {
              discard: (s) => discardOrphans.mutate(s),
              discardAll: () => discardOrphans.mutate(),
              versionCount: versionOrphans,
              busy: discardOrphans.isPending,
            } : undefined}
          >
            <QueuedList projectId={pid} versionId={versionId} slotRefs={slotRefs} />
          </CorrectionsTab>
        ) : (
          <OutlineTab nodes={outline} activeId={activeId} counts={isEditing ? counts : null} onJump={jumpToSection} />
        )}
      </RightPanel>

      {/* ── Review and approval dialogs ── */}
      {dialog === 'assign' && (
        <AssignReviewerDialog projectId={pid} documents={[doc]} allDocuments={allRailDocs} onClose={() => setDialog(null)} />
      )}
      {dialog === 'approve' && (
        <ApproveDialog
          projectId={pid}
          versionId={versionId}
          doc={doc}
          corrections={docCorrectionCount}
          readiness={docReadiness}
          readinessFailed={docReadinessFailed}
          meId={meId}
          words={words}
          onClose={() => setDialog(null)}
          onDone={() => setEditing(false)}
        />
      )}

      {/* ── Word files: what an update writes, asked before it starts ── */}
      {ask && versionId && (
        <UpdateWordFilesDialog
          projectId={pid}
          versionId={versionId}
          ask={ask}
          files={files}
          rebuildCount={allRailDocs.filter((d) => d.status !== 'approved').length}
          documentId={doc.id}
          words={words}
          onClose={() => setAsk(null)}
        />
      )}
      {dialog === 'changes' && <RequestChangesDialog projectId={pid} doc={doc} onClose={() => setDialog(null)} />}
      {dialog === 'reopen' && (
        <ReopenDialog projectId={pid} doc={doc} onClose={() => setDialog(null)} onDone={() => setEditing(false)} />
      )}

      {/* ── One flowchart's labels (edit mode) ── */}
      {openChart && (
        <FlowchartLabelDialog
          chart={openChart}
          projectId={pid}
          versionId={versionId}
          locked={locked}
          userName={userName}
          onClose={() => setOpenChart(null)}
        />
      )}
    </div>
    </EditContext.Provider>
  )
}
