import { useCallback, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useDocument, useDocuments, useDocumentRender, useTeam, useProject } from '../../hooks/useProjects'
import { useProjectViewState } from '../../hooks/useProjectViewState'
import {
  useApproveDoc, useSelfAssign, useAssignReviewers, useDownloadDoc,
} from '../../hooks/useDocumentMutations'
import {
  reexportActive, useExportReadiness, useSaveSlot, useUndoSlot, useVersionOverrides,
} from '../../hooks/useReview'
import { useAuthStore } from '../../store/auth'
import { useUIStore } from '../../store/ui'
import { DocTreePanel } from '../../components/shell/DocTreePanel'
import { SubbarCta } from '../../components/shell/SubbarCta'
import { groupDocsByProcess, buildAssigneeOptions, docxFileName } from '../../lib/docTree'
import { Card, Icon, Skeleton, Text } from '../../components/ui'
import { cn } from '../../lib/cn'
import type { FlowchartEntry, Slot } from '../../types'
import { Swe4Body, Swe4Strip } from './components/Swe4Reader'
import { RichSectionView } from './components/Sections'
import { MetaBanner } from './components/MetaBanner'
import { ReviewTracker } from './components/ReviewTracker'
import { AssignReviewersPanel } from './components/AssignReviewersPanel'
import { RightPanel, type PanelTab } from './components/RightPanel'
import { OutlineTab } from './components/OutlineTab'
import { CorrectionsTab } from './components/CorrectionsTab'
import { EditBar, ReadinessBanner } from './components/ReviewBars'
import { FlowchartLabelDialog } from './components/FlowchartLabelDialog'
import { TreeRail } from './components/TreeRail'
import { EditContext, type EditApi } from './editContext'
import { buildOutline, docCorrections, docSlots, outlineIds, unitCorrectionCounts } from './outline'
import { useScrollSpy } from './useScrollSpy'

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
  const { data: doc, isLoading } = useDocument(pid, docId ?? '')
  const { data: rich } = useDocumentRender(pid, docId ?? '')
  const { data: team } = useTeam(pid)
  const { viewVersion, selectedCommit, pageState } = useProjectViewState(pid)
  // The left rail lists every doc of THIS document's version, so you can jump between documents
  // without going back. Not the Subbar's: while a newer run is going, the Subbar shows that
  // run's draft, which has no documents, and the rail said "No documents" beside an open one.
  const railVersionId = doc?.versionId ?? viewVersion?.id
  const { data: railDocs } = useDocuments(pid, railVersionId ? { versionId: railVersionId } : undefined)
  const versionId = doc?.versionId ?? ''

  const approveDoc = useApproveDoc(pid)
  const selfAssign = useSelfAssign(pid)
  const assignReviewers = useAssignReviewers(pid)
  const downloadDoc = useDownloadDoc(pid)
  const { data: readiness } = useExportReadiness(pid, versionId || undefined)
  // `mutateAsync`/`mutate` are stable across renders; the mutation objects are not, and the edit
  // context below must not change on every job poll (it would re-render every correctable text).
  const { mutateAsync: saveText } = useSaveSlot(pid, versionId)
  const { mutate: undoText } = useUndoSlot(pid, versionId)

  const isAdmin = project?.userRole === 'admin'
  const isDeveloper = project?.userRole === 'developer'
  const meName = useAuthStore((s) => s.user?.name ?? '')
  const panelCollapsed = useUIStore((s) => s.inspectorPanelCollapsed)
  const togglePanel = useUIStore((s) => s.toggleInspectorPanel)
  const treeFolded = useUIStore((s) => s.docTreeFolded)
  const setTreeFolded = useUIStore((s) => s.setDocTreeFolded)

  const [canvasEl, setCanvasEl] = useState<HTMLElement | null>(null)
  const [assignOpen, setAssignOpen] = useState(false)
  const [assigneeFilter, setAssigneeFilter] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [openChart, setOpenChart] = useState<FlowchartEntry | null>(null)
  const [tab, setTab] = useState('outline')

  const isSwe4 = doc?.process === 'SWE.4'
  const sections = useMemo(() => rich?.sections ?? [], [rich])
  const slots = useMemo(() => (isSwe4 ? [] : docSlots(sections)), [sections, isSwe4])
  const canEdit = !isSwe4 && slots.length > 0 && !!versionId
  const { data: overrides, isLoading: overridesLoading, isError: overridesError } =
    useVersionOverrides(pid, canEdit ? versionId : undefined)
  const corrections = useMemo(
    () => docCorrections(overrides ?? [], sections, rich?.cover.group ?? ''), [overrides, sections, rich])
  const counts = useMemo(() => unitCorrectionCounts(corrections.inForce, sections), [corrections, sections])
  // The outline stops at units for SWE.4 (as the mockup): a line per test spec would bury it.
  const outline = useMemo(() => buildOutline(sections, isSwe4 ? 3 : 4), [sections, isSwe4])
  const ids = useMemo(() => outlineIds(outline), [outline])
  const activeId = useScrollSpy(canvasEl, ids)

  const names = useMemo(() => new Map((team ?? []).map((m) => [m.userId ?? m.id, m.name])), [team])
  const userName = useCallback((id: string | null) => (id ? names.get(id) ?? '' : ''), [names])
  const locked = pageState === 'running' || reexportActive(readiness)
  const editApi: EditApi = useMemo(() => ({
    editing: editing && canEdit,
    locked,
    projectId: pid,
    versionId,
    save: (slot: Slot, text: string) => saveText({ slot, text }),
    undo: (slot: Slot) => undoText(slot),
    openFlowchart: setOpenChart,
    userName,
  }), [editing, canEdit, locked, pid, versionId, saveText, undoText, userName])

  function jumpToSection(id: string) {
    document.getElementById(`sec-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  function jumpToSlot(slot: Slot) {
    const all = Array.from(document.querySelectorAll<HTMLElement>('[data-slot-key], [data-flowchart-id]'))
    reveal(slot.kind === 'nodeLabel'
      ? all.find((el) => el.dataset.flowchartId === slot.flowchartId)
      : all.find((el) => el.dataset.slotKey === slot.key))
  }

  // Rail data (assignee filter shared with the dropdown, mirrors DocumentsPage).
  const allRailDocs = railDocs ?? []
  const railAssignee = assigneeFilter ?? (isDeveloper ? meName : '')
  const railGroups = groupDocsByProcess(railAssignee ? allRailDocs.filter((d) => d.assignee === railAssignee) : allRailDocs)
  const railAssignees = buildAssigneeOptions(allRailDocs)

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

  const inReview = doc.status === 'in_review'
  const isUnchanged = doc.status === 'unchanged' || doc.status === 'draft'
  // The document's own version (its cover says the same), not the Subbar's pick.
  const refLabel = rich?.cover.version ?? doc.version
  const assignedToMe = !!meName && doc.assignee === meName
  const members = (team ?? []).filter((m) => !m.pending)
  const docStale = !!readiness?.stale
  const isEditing = editing && canEdit

  const tabs: PanelTab[] = [
    { id: 'outline', label: 'Outline' },
    ...(inReview ? [{ id: 'review', label: 'Review' }] : []),
    ...(canEdit ? [{ id: 'corr', label: 'Corrections', count: corrections.inForce.length }] : []),
  ]
  const activeTab = tabs.some((t) => t.id === tab) ? tab : 'outline'

  return (
    <EditContext.Provider value={editApi}>
    <div className="flex-1 flex overflow-hidden min-h-0 relative">

      {/* ── Edit / Done (review & update): SWE.3 only; SWE.4 follows its flowchart labels ── */}
      {canEdit && (
        <SubbarCta>
          <button
            onClick={() => setEditing((v) => !v)}
            aria-pressed={isEditing}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em] border',
              isEditing ? 'bg-secondary border-secondary text-on-secondary hover:bg-secondary-container' : 'border-secondary text-secondary bg-white hover:bg-surface-container-low',
            )}
          >
            <Icon name={isEditing ? 'check' : 'edit'} size={14} />
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
          meName={meName}
          isDeveloper={!!isDeveloper}
          activeDocId={doc.id}
          onPickAssignee={setAssigneeFilter}
          onOpenDoc={(d) => navigate(`/projects/${pid}/documents/${d.id}`)}
          onFold={() => setTreeFolded(true)}
        />
      )}

      {/* ── Document canvas ── */}
      <main ref={setCanvasEl} className="flex-1 overflow-y-auto bg-surface-container-low">
        {isEditing && <EditBar locked={locked} />}
        <div className="max-w-5xl mx-auto px-6 py-8">
          {versionId && (
            <ReadinessBanner projectId={pid} versionId={versionId} readiness={readiness} isAdmin={!!isAdmin} />
          )}
          <div className="bg-white rounded-xl border border-outline-variant overflow-hidden shadow-[0_1px_4px_rgba(4,22,39,.06)]">

            {/* Cover header */}
            <div className="px-8 pt-10 pb-8 border-b border-outline-variant">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <Text as="p" variant="label" className="text-on-surface-variant tracking-[0.1em] mb-2">
                    {(rich?.cover.process ?? doc.process)} · <span className="font-mono">{rich?.cover.version ?? refLabel}</span>
                  </Text>
                  <h1 className="text-[28px] font-bold leading-tight tracking-[-0.02em] text-on-surface">{doc.name}</h1>
                  <p className="text-sm text-on-surface-variant mt-1">{rich?.cover.subtitle ?? doc.subtitle ?? 'Software Detailed Design Specification'}</p>
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
                  <button
                    onClick={() => downloadDoc(doc.id, docxFileName(doc))}
                    title={docStale ? 'This Word file does not have the latest corrections yet: re-export first.' : undefined}
                    className="relative flex items-center gap-1.5 px-3 py-2 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors font-mono text-caption font-medium"
                  >
                    <Icon name="download" size={15} />
                    DOCX
                    {docStale && <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-amber border-2 border-white" aria-label="Out of date" />}
                  </button>
                  {!isUnchanged && (
                    <button
                      onClick={() => navigate(`/projects/${pid}/compare`)}
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
            <div className="px-8 py-10 space-y-12">
              {!rich ? (
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
          <ReviewTracker
            sections={doc.sections}
            progress={doc.reviewProgress}
            reviewer={doc.assignee}
            reviewerInitials={doc.assigneeInitials}
            isAdmin={!!isAdmin}
            assignedToMe={assignedToMe}
            onMarkComplete={() => approveDoc.mutate(doc.id)}
            onReassign={() => setAssignOpen(true)}
            onAssignToMe={() => selfAssign.mutate(doc.id)}
            onJump={jumpToSection}
          />
        ) : activeTab === 'corr' ? (
          <CorrectionsTab
            inForce={corrections.inForce}
            orphans={corrections.orphans}
            isLoading={overridesLoading}
            isError={overridesError}
            userName={userName}
            onJump={jumpToSlot}
          />
        ) : (
          <OutlineTab nodes={outline} activeId={activeId} counts={isEditing ? counts : null} onJump={jumpToSection} />
        )}
      </RightPanel>

      {/* ── Assign reviewers slide-in ── */}
      {assignOpen && (
        <AssignReviewersPanel
          members={members}
          refLabel={refLabel}
          shortSha={selectedCommit?.shortSha ?? viewVersion?.shortSha}
          busy={assignReviewers.isPending}
          onClose={() => setAssignOpen(false)}
          onAssign={(userId) =>
            assignReviewers.mutate({ docId: doc.id, userIds: [userId] }, { onSuccess: () => setAssignOpen(false) })
          }
        />
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
