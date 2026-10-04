import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useDocuments, useCommits, useTeam, useVersions } from '../../hooks/useProjects'
import { useDownloadAll, useDownloadDoc } from '../../hooks/useDocumentMutations'
import { useApproveDocuments, useClaimDocument, useDocumentsReadiness } from '../../hooks/useApproval'
import { reexportActive, useExportReadiness } from '../../hooks/useReview'
import { SubbarCta } from '../../components/shell/SubbarCta'
import { useProjectViewState } from '../../hooks/useProjectViewState'
import { useAuthStore } from '../../store/auth'
import { Card, Icon, TableSkeleton, Text } from '../../components/ui'
import { LoadError } from '../../components/LoadError'
import { failedLoad } from '../../lib/failedLoad'
import { DocTreePanel } from '../../components/shell/DocTreePanel'
import { AssignReviewerDialog } from '../../components/review/AssignReviewerDialog'
import { NEEDS_REVIEWER, buildReviewerOptions, docxFileName, groupDocsByProcess } from '../../lib/docTree'
import { cn } from '../../lib/cn'
import { componentWordFileStale, wordFileOutOfDate } from '../../lib/reviewStatus'
import type { Document, ReviewStatus } from '../../types'
import { bulkApprovePlan, filterDocuments } from './helpers'
import { DocRow } from './components/DocRow'
import { VersionApprovalBar } from './components/VersionApprovalBar'
import { BulkApproveDialog } from './components/BulkApproveDialog'
import { StatusFilter } from './components/StatusFilter'
import { ComponentsPanel } from './components/ComponentsPanel'

const PROCESSES = ['All', 'SYS.1', 'SYS.2', 'SWE.1', 'SWE.2', 'SWE.3', 'SWE.4']

/** Download All while the version's Word files lack corrections (R9 `stale`). */
const PREVIOUS_WORD_FILES = 'Previous Word files — the corrections are not in them yet'

// Fixed layout, widths including the cells' padding: the actions column holds four icon buttons
// (~120px), Status the widest badge ("Ready for approval"). Declared narrower a column took its
// width anyway, squeezed the Document column, and every row wrapped to two lines.
const COLUMNS: [string, number | undefined][] = [
  ['Document', undefined], ['Process', 76], ['Reviewer', 156], ['Status', 168], ['Last activity', 170], ['', 146],
]

export function DocumentsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const pid = projectId ?? ''
  const navigate = useNavigate()
  const goOverview = () => navigate(`/projects/${pid}/overview`)

  const projectQuery = useProject(pid)
  const { data: project } = projectQuery
  const versionsQuery = useVersions(pid)
  const { data: commits } = useCommits(pid)
  const { data: team } = useTeam(pid)
  // The displayed version/state follows the Subbar picker (shared via the UI store).
  const { pageState, viewVersion, selectedCommit, isLoading: viewLoading } = useProjectViewState(pid)
  // Scope documents to the picked version so switching versions in the Subbar
  // refetches the right set (default = latest version).
  const documentsQuery = useDocuments(
    pid,
    viewVersion?.id ? { versionId: viewVersion.id } : undefined,
  )
  const { data: documents } = documentsQuery
  // The documents wait for a version: while the versions load, that is loading too.
  const isLoading = documentsQuery.isLoading || (!viewVersion && viewLoading)
  // The project, its versions (which say what state the page is in) and the documents: a failed
  // read of any is shown as one, with Retry — not as "No documents yet" or "No documents found".
  const failed = failedLoad(projectQuery, versionsQuery, documentsQuery)
  const downloadDoc = useDownloadDoc(pid)
  const downloadAll = useDownloadAll(pid)
  const claim = useClaimDocument(pid)
  const approveMany = useApproveDocuments(pid)

  // Role is per-project (API's my_role → project.userRole); "me" is the signed-in user's id.
  const isAdmin = project?.userRole === 'admin'
  const isDeveloper = project?.userRole === 'developer'
  const meId = useAuthStore((s) => s.user?.id ?? '')
  const names = useMemo(() => new Map((team ?? []).map((m) => [m.userId ?? m.id, m.name])), [team])
  const nameOf = (id: string) => names.get(id)

  const [activeProcess, setActiveProcess] = useState('All')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<Set<ReviewStatus>>(new Set())
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Reviewer filter shared by the left rail + the dev quick-toggle: a user id, `none` (Needs a
  // reviewer) or '' (all). `null` = the role default (developers → their own, admins → all).
  const [assigneeFilter, setAssigneeFilter] = useState<string | null>(null)
  const [assignFor, setAssignFor] = useState<Document[] | null>(null)
  const [bulkOpen, setBulkOpen] = useState(false)

  const effectiveAssignee = assigneeFilter ?? (isDeveloper ? meId : '')

  const all = useMemo(() => documents ?? [], [documents])
  const filtered = filterDocuments(all, {
    process: activeProcess, statuses: statusFilter, reviewer: effectiveAssignee, search,
  })
  const reviewerOptions = buildReviewerOptions(all)
  const treeGroups = groupDocsByProcess(filtered)

  // Bulk actions act on what you see: a selected row a filter hides is not acted on.
  const selectedDocs = filtered.filter((d) => selected.has(d.id))
  const allSelected = selectedDocs.length === filtered.length && filtered.length > 0
  const someSelected = selectedDocs.length > 0 && !allSelected

  // Approve…: only Ready for approval with an up-to-date Word file (R9). The version's R9 says
  // so for all at once; when it is stale, each candidate's own (A15) is read as the dialog opens.
  // Every role reads it: Download says when it gives the previous Word file — a row when R9 names
  // its component (`staleComponents`), Download All when the version is behind at all.
  const { data: versionReadiness, isError: versionReadinessFailed } =
    useExportReadiness(pid, viewVersion?.id)
  // Download All: the approved documents' files are the approved ones; the rest are previous.
  const allStale = wordFileOutOfDate(versionReadiness) && all.some((d) => d.status !== 'approved')
  const candidates = selectedDocs.filter((d) => d.status === 'submitted')
  const perDoc = useDocumentsReadiness(pid, candidates,
    bulkOpen && (versionReadinessFailed || wordFileOutOfDate(versionReadiness)))
  const plan = bulkApprovePlan(selectedDocs, {
    versionReadiness,
    readinessById: perDoc.byId,
    failed: perDoc.failed,
    reexporting: reexportActive(versionReadiness),
  })
  const approveLabel = plan.ready.length && !plan.checking.length ? `Approve ${plan.ready.length}…` : 'Approve…'

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  function toggleStatus(s: ReviewStatus) {
    setStatusFilter((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }
  const openDoc = (d: Document, review = false) =>
    navigate(`/projects/${projectId}/documents/${d.id}${review ? '?tab=review' : ''}`)

  async function downloadSelected() {
    // One at a time; a failure is reported by the hook and the rest still download.
    for (const d of selectedDocs) await downloadDoc(d.id, docxFileName(d))
  }
  function approveSelected() {
    approveMany.mutate({ docIds: plan.ready.map((d) => d.id) }, {
      onSuccess: () => { setBulkOpen(false); setSelected(new Set()) },
    })
  }

  // Download is available to everyone; Assign/Approve are admin-only (design).
  const bulkActions = [
    { icon: 'download', label: 'Download', onClick: downloadSelected },
    ...(isAdmin
      ? [
          { icon: 'person_add', label: 'Assign…', onClick: () => setAssignFor(selectedDocs) },
          { icon: 'task_alt', label: approveLabel, onClick: () => setBulkOpen(true) },
        ]
      : []),
  ]

  // ── A read failed: say so, with Retry (an empty page would be a wrong answer) ──
  if (failed) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="p-6">
          <Card>
            <LoadError what="the documents" error={failed.error} retrying={failed.retrying} onRetry={failed.retry} />
          </Card>
        </div>
      </div>
    )
  }

  // ── NOT-RUN state: the picked commit/version has no documents yet ──
  if (pageState === 'never') {
    const runRef = viewVersion?.tag ?? (selectedCommit ? `commit ${selectedCommit.shortSha}` : project?.defaultBranch ?? '')
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="p-6">
          <Card className="overflow-hidden">
            <div className="py-20 flex flex-col items-center text-center gap-5">
              <div className="w-16 h-16 rounded-2xl bg-surface-container-low border border-outline-variant flex items-center justify-center">
                <Icon name="play_circle" size={32} className="text-on-surface-variant" />
              </div>
              <div>
                <Text as="p" variant="heading" className="text-on-surface mb-1">No documents yet</Text>
                <Text as="p" variant="caption" className="font-mono mt-1">
                  Run analysis on <span className="font-mono text-caption text-secondary">{runRef}</span> to generate design specifications
                </Text>
              </div>
              <button
                onClick={goOverview}
                className="flex items-center gap-2 px-5 py-2.5 bg-secondary hover:bg-secondary-container text-white rounded-xl font-mono text-caption transition-colors"
              >
                <Icon name="play_arrow" size={16} />
                Run Analysis
              </button>
            </div>
          </Card>
        </div>
      </div>
    )
  }

  // ── RUNNING state: the picked version is still being generated (mockup: "Generating document") ──
  if (pageState === 'running' && !isLoading && all.length === 0) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="p-6">
          {/* Staged generation: once the model is built, which components are being made. */}
          {viewVersion?.id && <ComponentsPanel key={viewVersion.id} projectId={pid} versionId={viewVersion.id} isAdmin={!!isAdmin} />}
          <Card className="overflow-hidden">
            <div className="py-20 flex flex-col items-center text-center gap-5">
              <div className="w-16 h-16 rounded-2xl bg-surface-container-low border border-outline-variant flex items-center justify-center">
                <Icon name="autorenew" size={32} className="text-secondary animate-spin" />
              </div>
              <div>
                <Text as="p" variant="heading" className="text-on-surface mb-1">Generating documents</Text>
                <Text as="p" variant="caption" className="font-mono mt-1">
                  <span className="text-secondary">{viewVersion?.tag}</span> is being generated. Its documents appear here when the run completes.
                </Text>
              </div>
              <button
                onClick={goOverview}
                className="flex items-center gap-2 px-5 py-2.5 border border-outline-variant bg-white hover:bg-surface-container text-on-surface rounded-xl font-mono text-caption transition-colors"
              >
                <Icon name="monitoring" size={16} />
                View progress
              </button>
            </div>
          </Card>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      {/* The page's Subbar action (mockup: "Download All") — every DOCX of the viewed version. */}
      {viewVersion?.id && all.length > 0 && (
        <SubbarCta>
          <button
            onClick={() => downloadAll.mutate({ versionId: viewVersion.id!, fileName: `${project?.name ?? pid}-${viewVersion.tag}.zip` })}
            disabled={downloadAll.isPending}
            title={allStale ? `Download all: ${PREVIOUS_WORD_FILES}` : undefined}
            className="relative flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container rounded-lg transition-colors text-on-secondary font-mono text-caption font-bold tracking-[0.04em] disabled:opacity-60"
          >
            <Icon name="download" size={14} />
            {downloadAll.isPending ? 'PREPARING…' : 'DOWNLOAD ALL'}
            {allStale && (
              <>
                <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-amber border-2 border-white" aria-hidden />
                <span className="sr-only">{PREVIOUS_WORD_FILES}</span>
              </>
            )}
          </button>
        </SubbarCta>
      )}
      <DocTreePanel
        groups={treeGroups}
        assigneeOptions={reviewerOptions}
        effectiveAssignee={effectiveAssignee}
        meId={meId}
        isDeveloper={!!isDeveloper}
        onPickAssignee={setAssigneeFilter}
        onOpenDoc={(d) => openDoc(d)}
      />
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="p-6">

        {/* ── Stale banner: docs generated from an older commit than HEAD ── */}
        {pageState === 'stale' && (
          <div className="mb-4 flex items-center gap-3 px-4 py-3 rounded-xl border bg-[#fffbeb] border-[#fcd34d]">
            <Icon name="warning" size={18} className="text-[#b45309] flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <p className="font-mono text-caption text-[#92400e]">
                Documents generated from{' '}
                <code className="font-mono text-label bg-[#fef3c7] px-1 py-px rounded-[3px]">{viewVersion?.shortSha ?? '—'}</code>
                {commits?.[0] && (
                  <>
                    {' '}— HEAD is now at{' '}
                    <code className="font-mono text-label bg-[#fef3c7] px-1 py-px rounded-[3px]">{commits[0].shortSha}</code>
                  </>
                )}
                {viewVersion?.newCommitsSince
                  ? ` · ${viewVersion.newCommitsSince} commit${viewVersion.newCommitsSince !== 1 ? 's' : ''} ahead`
                  : ''}
              </p>
            </div>
            <button
              onClick={goOverview}
              className="flex-shrink-0 flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-white bg-[#b45309] font-mono text-label font-semibold whitespace-nowrap"
            >
              <Icon name="play_arrow" size={12} />
              Re-run
            </button>
          </div>
        )}

        {/* Staged generation: the version's components and the documents still to make. */}
        {viewVersion?.id && <ComponentsPanel key={viewVersion.id} projectId={pid} versionId={viewVersion.id} isAdmin={!!isAdmin} />}

        <Card className="overflow-hidden">

          {/* ── Card header ── */}
          <div className="px-5 pt-4 pb-0 border-b border-outline-variant">
            <div className="flex items-center justify-between mb-3">
              <div>
                <Text as="h2" variant="heading" className="text-on-surface">Documents</Text>
                <Text as="p" variant="caption" className="font-mono mt-0.5">
                  {filtered.length} document{filtered.length !== 1 ? 's' : ''}
                  {isDeveloper && (
                    <>
                      {' · '}
                      <button
                        onClick={() => setAssigneeFilter(effectiveAssignee === meId ? '' : meId)}
                        className="text-secondary hover:underline transition-colors font-mono text-caption"
                      >
                        {effectiveAssignee === meId ? 'Show all' : 'My reviews'}
                      </button>
                    </>
                  )}
                  {viewVersion?.tag ? ` · ${viewVersion.tag}` : project?.latestVersion ? ` · ${project.latestVersion}` : ''} · {project?.name ?? '…'}
                </Text>
              </div>
              <div className="flex items-center gap-2">
                <StatusFilter value={statusFilter} onToggle={toggleStatus} onClear={() => setStatusFilter(new Set())} />
                {/* Search */}
                <div className="flex items-center gap-1.5 px-2.5 py-1.5 border border-outline-variant rounded-lg bg-white hover:border-secondary transition-colors min-w-[180px]">
                  <Icon name="search" size={14} className="text-on-surface-variant flex-shrink-0" />
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    type="text"
                    placeholder="Search documents…"
                    className="flex-1 bg-transparent outline-none text-on-surface placeholder:text-on-surface-variant font-mono text-caption"
                  />
                </div>
              </div>
            </div>

            {/* Process tabs */}
            <div className="flex items-center -mb-px overflow-x-auto" role="tablist" aria-label="Filter by process">
              {PROCESSES.map((p) => {
                const active = activeProcess === p
                return (
                  <button
                    key={p}
                    role="tab"
                    aria-selected={active}
                    onClick={() => setActiveProcess(p)}
                    className={cn(
                      'transition-colors whitespace-nowrap px-3.5 py-2 font-mono text-caption font-semibold border-b-2',
                      active ? 'border-secondary text-secondary' : 'border-transparent text-outline',
                    )}
                  >
                    {p}
                  </button>
                )
              })}
            </div>
          </div>

          {/* ── The version's approval, derived from its documents ── */}
          <VersionApprovalBar
            version={viewVersion}
            docs={all}
            onOnlyStatus={(s) => setStatusFilter(new Set([s]))}
            onNeedsReviewer={() => setAssigneeFilter(NEEDS_REVIEWER)}
          />

          {/* ── Batch bar ── */}
          {selectedDocs.length > 0 && (
            <div className="bg-secondary border-b border-secondary-container px-5 py-2.5 flex items-center justify-between" role="toolbar" aria-label="Bulk actions">
              <div className="flex items-center gap-3">
                <span className="text-on-secondary font-semibold font-mono text-xs">{selectedDocs.length} selected</span>
                <div className="w-px h-4 bg-on-secondary opacity-30" aria-hidden />
                {bulkActions.map(({ icon, label, onClick }) => (
                  <button
                    key={icon}
                    onClick={onClick}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors text-on-secondary font-mono text-caption font-medium bg-white/12 hover:bg-white/20"
                  >
                    <Icon name={icon} size={13} />
                    {label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setSelected(new Set())}
                className="flex items-center gap-1 text-on-secondary opacity-70 hover:opacity-100 transition-opacity font-mono text-caption"
              >
                <Icon name="close" size={14} />
                Clear
              </button>
            </div>
          )}

          {/* ── Table ── */}
          <div className="overflow-x-auto">
            {isLoading ? (
              <TableSkeleton rows={8} cols={7} />
            ) : (
              <table className="w-full table-fixed">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    <th className="px-3 py-3 w-10">
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={allSelected}
                        ref={(el) => { if (el) el.indeterminate = someSelected }}
                        onChange={(e) => setSelected(e.target.checked ? new Set(filtered.map((d) => d.id)) : new Set())}
                        className="accent-secondary w-[15px] h-[15px] cursor-pointer"
                      />
                    </th>
                    {COLUMNS.map(([h, w], i) => (
                      <th
                        key={i}
                        className="text-left px-3 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em] whitespace-nowrap"
                        // eslint-disable-next-line no-restricted-syntax -- per-column layout width from the header config
                        style={{ width: w }}
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((doc) => (
                    <DocRow
                      key={doc.id}
                      doc={doc}
                      selected={selected.has(doc.id)}
                      isAdmin={!!isAdmin}
                      isDeveloper={!!isDeveloper}
                      meId={meId}
                      nameOf={nameOf}
                      claimPending={claim.isPending}
                      wordFileStale={componentWordFileStale(versionReadiness, doc.group)}
                      onToggle={() => toggle(doc.id)}
                      onOpen={() => openDoc(doc)}
                      onReview={() => openDoc(doc, true)}
                      onCompare={() => navigate(`/projects/${projectId}/compare?doc=${doc.id}`)}
                      onDownload={() => downloadDoc(doc.id, docxFileName(doc))}
                      onAssign={() => setAssignFor([doc])}
                      onClaim={() => claim.mutate(doc.id)}
                    />
                  ))}
                </tbody>
              </table>
            )}

            {!isLoading && filtered.length === 0 && (
              <div className="py-14 flex flex-col items-center text-center gap-4">
                <div className="w-12 h-12 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
                  <Icon name="search_off" size={24} className="text-on-surface-variant" />
                </div>
                <div>
                  <Text as="p" variant="heading" className="text-on-surface">No documents found</Text>
                  <Text as="p" variant="caption" className="font-mono mt-1">
                    Try a different process, status, reviewer or search term.
                  </Text>
                </div>
              </div>
            )}
          </div>

          {/* ── Footer ── */}
          {!isLoading && filtered.length > 0 && (
            <div className="px-5 py-3.5 border-t border-outline-variant flex items-center justify-between bg-white">
              <Text as="p" variant="caption" className="font-mono">
                Showing {filtered.length} of {all.length} document{all.length !== 1 ? 's' : ''}
              </Text>
            </div>
          )}
        </Card>
        </div>
      </div>

      {assignFor && (
        <AssignReviewerDialog
          projectId={pid}
          documents={assignFor}
          allDocuments={all}
          onClose={() => setAssignFor(null)}
          onDone={() => setSelected(new Set())}
        />
      )}
      {bulkOpen && (
        <BulkApproveDialog
          plan={plan}
          busy={approveMany.isPending}
          onConfirm={approveSelected}
          onClose={() => setBulkOpen(false)}
        />
      )}
    </div>
  )
}
