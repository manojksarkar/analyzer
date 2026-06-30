import { useState, useRef, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useDocuments, useVersions, useCommits } from '../hooks/useProjects'
import { useApproveDocs, useDownloadDoc, useSelfAssign } from '../hooks/useDocumentMutations'
import { useProjectViewState } from '../hooks/useProjectViewState'
import { useAuthStore } from '../store/auth'
import { Card, Icon, TableSkeleton, Text, toast } from '../components/ui'
import { ProcessBadge } from '../components/ui/Badge'
import { DocTreePanel } from '../components/shell/DocTreePanel'
import { groupDocsByProcess, buildAssigneeOptions } from '../lib/docTree'
import { cn } from '../lib/cn'
import type { DocStatus, Document } from '../types'

const PROCESSES = ['All', 'SYS.1', 'SYS.2', 'SWE.1', 'SWE.3']

/* status → {label, icon, badge classes} (matches design .badge-*) */
const STATUS_BADGE: Record<string, { label: string; icon: string; cls: string }> = {
  approved:  { label: 'Approved',  icon: 'check_circle',    cls: 'bg-[#f0fdf9] text-[#00a572] border-[#86efac]' },
  in_review: { label: 'In Review', icon: 'rate_review',     cls: 'bg-[#fff8e6] text-[#b45309] border-[#f59e0b]' },
  complete:  { label: 'Approved',  icon: 'check_circle',    cls: 'bg-[#f0fdf9] text-[#00a572] border-[#86efac]' },
  unchanged: { label: 'Unchanged', icon: 'horizontal_rule', cls: 'bg-[#f3f4f6] text-outline border-outline-variant' },
  draft:     { label: 'Unchanged', icon: 'horizontal_rule', cls: 'bg-[#f3f4f6] text-outline border-outline-variant' },
}

function StatusBadge({ status }: { status: DocStatus }) {
  const s = STATUS_BADGE[status] ?? STATUS_BADGE.unchanged
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 uppercase px-2 py-0.5 rounded-[3px] font-mono text-label font-bold tracking-[0.04em] whitespace-nowrap border',
        s.cls,
      )}
    >
      <Icon name={s.icon} size={10} />
      {s.label}
    </span>
  )
}

/* Normalize the various DocStatus values into the 3 filterable buckets */
function statusBucket(s: DocStatus): 'approved' | 'in_review' | 'unchanged' {
  if (s === 'approved' || s === 'complete') return 'approved'
  if (s === 'in_review') return 'in_review'
  return 'unchanged'
}

export function DocumentsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const pid = projectId ?? ''
  const navigate = useNavigate()
  const goOverview = () => navigate(`/projects/${pid}/overview`)

  const { data: project } = useProject(pid)
  const { data: versions } = useVersions(pid)
  const { data: commits } = useCommits(pid)
  // The displayed version/state follows the Subbar picker (shared via the UI store).
  const { pageState, viewVersion, selectedCommit } = useProjectViewState(pid)
  // Scope documents to the picked version so switching versions in the Subbar
  // refetches the right set (default = latest version).
  const { data: documents, isLoading } = useDocuments(
    pid,
    viewVersion?.id ? { versionId: viewVersion.id } : undefined,
  )
  const approveDocs = useApproveDocs(pid)
  const downloadDoc = useDownloadDoc(pid)
  const selfAssign = useSelfAssign(pid)

  // Role is per-project (API's my_role → project.userRole); "me" matches by name.
  const isAdmin = project?.userRole === 'admin'
  const isDeveloper = project?.userRole === 'developer'
  const meName = useAuthStore((s) => s.user?.name ?? '')

  // version_id → tag, so the Version column shows "v1.2.0" not "ver3".
  const tagById = Object.fromEntries((versions ?? []).map((v) => [v.id ?? '', v.tag]))
  const versionLabel = (idOrTag: string) => tagById[idOrTag] ?? idOrTag
  const versionTag = viewVersion?.tag ?? project?.latestVersion ?? ''

  const [activeProcess, setActiveProcess] = useState('All')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<Set<'approved' | 'in_review' | 'unchanged'>>(new Set())
  const [statusOpen, setStatusOpen] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  // Assignee filter shared by the left rail + the dev quick-toggle. `null` = use
  // the role default (developers → their own docs, admins → everyone).
  const [assigneeFilter, setAssigneeFilter] = useState<string | null>(null)

  const statusRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (statusRef.current && !statusRef.current.contains(e.target as Node)) setStatusOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  // Until the user picks, developers default to their own docs and admins to all.
  const effectiveAssignee = assigneeFilter ?? (isDeveloper ? meName : '')

  const all = documents ?? []
  const filtered = all.filter((d) => {
    if (activeProcess !== 'All' && d.process !== activeProcess) return false
    if (statusFilter.size > 0 && !statusFilter.has(statusBucket(d.status))) return false
    if (effectiveAssignee && d.assignee !== effectiveAssignee) return false
    if (search && !d.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  // Distinct assignees (for the rail dropdown) + the process-grouped tree.
  const assigneeOptions = buildAssigneeOptions(all)
  const treeGroups = groupDocsByProcess(filtered)

  // Review progress for the in-review summary bar (whole version, not filtered).
  const reviewedCount = all.filter((d) => statusBucket(d.status) === 'approved').length
  const reviewPct = all.length ? Math.round((reviewedCount / all.length) * 100) : 0

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  function toggleStatus(s: 'approved' | 'in_review' | 'unchanged') {
    setStatusFilter((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }

  const allSelected = selected.size === filtered.length && filtered.length > 0
  const someSelected = selected.size > 0 && !allSelected

  function approveSelected() {
    approveDocs.mutate([...selected], { onSuccess: () => setSelected(new Set()) })
  }

  async function downloadSelected() {
    const docs = filtered.filter((d) => selected.has(d.id))
    for (const d of docs) {
      try { await downloadDoc(d.id, d.name) } catch { /* skip a single failure */ }
    }
  }

  // Download is available to everyone; Assign/Approve are admin-only (design).
  const bulkActions = [
    { icon: 'download', label: 'Download', onClick: downloadSelected },
    ...(isAdmin
      ? [
          { icon: 'person_add', label: 'Assign', onClick: () => toast.info('Assign reviewers', 'Open a document to assign reviewers.') },
          { icon: 'task_alt', label: 'Approve', onClick: approveSelected },
        ]
      : []),
  ]

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

  return (
    <div className="flex-1 flex overflow-hidden min-h-0">
      <DocTreePanel
        groups={treeGroups}
        assigneeOptions={assigneeOptions}
        effectiveAssignee={effectiveAssignee}
        meName={meName}
        isDeveloper={!!isDeveloper}
        onPickAssignee={setAssigneeFilter}
        onOpenDoc={(d) => navigate(`/projects/${projectId}/documents/${d.id}`)}
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
                        onClick={() => setAssigneeFilter(effectiveAssignee === meName ? '' : meName)}
                        className="text-secondary hover:underline transition-colors font-mono text-caption"
                      >
                        {effectiveAssignee === meName ? 'Show all' : 'My Docs'}
                      </button>
                    </>
                  )}
                  {versionTag ? ` · ${versionTag}` : ''} · {project?.name ?? '…'}
                </Text>
              </div>
              <div className="flex items-center gap-2">
                {/* Status filter */}
                <div className="relative" ref={statusRef}>
                  <button
                    onClick={() => setStatusOpen((v) => !v)}
                    className="flex items-center gap-1.5 px-3 py-2 border border-outline-variant rounded-lg bg-white hover:bg-surface-container-low transition-colors font-mono text-caption font-medium text-on-surface-variant"
                  >
                    <Icon name="filter_list" size={14} className="text-on-surface-variant" />
                    {statusFilter.size > 0 ? `Status (${statusFilter.size})` : 'Status'}
                    <Icon name="expand_more" size={13} className="text-on-surface-variant" />
                  </button>
                  {statusOpen && (
                    <div className="absolute right-0 bg-white border border-outline-variant rounded-lg overflow-hidden top-[calc(100%+6px)] z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)] min-w-[180px]">
                      <div className="py-1.5">
                        {([['approved', 'Approved'], ['in_review', 'In Review'], ['unchanged', 'Unchanged']] as const).map(([key, label]) => (
                          <button
                            key={key}
                            onClick={() => toggleStatus(key)}
                            className="w-full flex items-center justify-between px-3 py-2 hover:bg-surface-container-low text-on-surface font-mono text-caption"
                          >
                            <span>{label}</span>
                            {statusFilter.has(key) && <Icon name="check" size={14} className="text-secondary" />}
                          </button>
                        ))}
                      </div>
                      <div className="border-t border-outline-variant py-1">
                        <button
                          onClick={() => setStatusFilter(new Set())}
                          className="w-full text-left px-3 py-2 hover:bg-surface-container-low text-on-surface-variant font-mono text-caption"
                        >
                          Clear filter
                        </button>
                      </div>
                    </div>
                  )}
                </div>
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

          {/* ── In-review summary bar ── */}
          {pageState === 'in_review' && all.length > 0 && (
            <div className="px-5 py-3 border-b border-outline-variant flex items-center gap-4 bg-[#fffbeb]">
              <Icon name="rate_review" size={16} className="text-[#b45309] flex-shrink-0" />
              <div className="flex-1">
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-mono text-caption text-[#92400e]">
                    Review in progress · {reviewedCount} of {all.length} documents reviewed
                  </span>
                  <span className="font-mono text-caption text-[#b45309]">{reviewPct}%</span>
                </div>
                <div className="h-1.5 rounded-[3px] bg-surface-container overflow-hidden">
                  {/* eslint-disable-next-line no-restricted-syntax -- review progress width is data-driven */}
                  <div className="h-full rounded-[3px] bg-[#b45309]" style={{ width: `${reviewPct}%` }} />
                </div>
              </div>
            </div>
          )}

          {/* ── Batch bar ── */}
          {selected.size > 0 && (
            <div className="bg-secondary border-b border-secondary-container px-5 py-2.5 flex items-center justify-between" role="toolbar" aria-label="Bulk actions">
              <div className="flex items-center gap-3">
                <span className="text-on-secondary font-semibold font-mono text-xs">{selected.size} selected</span>
                <div className="w-px h-4 bg-on-secondary opacity-30" aria-hidden />
                {bulkActions.map(({ icon, label, onClick }) => (
                  <button
                    key={label}
                    onClick={onClick}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors text-on-secondary font-mono text-caption font-medium bg-white/12"
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
              <TableSkeleton rows={8} cols={8} />
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    <th className="px-4 py-3 w-10">
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={allSelected}
                        ref={(el) => { if (el) el.indeterminate = someSelected }}
                        onChange={(e) => setSelected(e.target.checked ? new Set(filtered.map((d) => d.id)) : new Set())}
                        className="accent-secondary w-[15px] h-[15px] cursor-pointer"
                      />
                    </th>
                    {[['Document', undefined], ['Process', 100], ['Version', 90], ['Assignee', 155], ['Status', 110], ['Due Date', 100], ['', 90]].map(([h, w], i) => (
                      <th
                        key={i}
                        className="text-left px-4 py-3 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.07em]"
                        // eslint-disable-next-line no-restricted-syntax -- per-column layout width from the header config
                        style={{ width: w as number | undefined }}
                      >
                        {h as string}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((doc) => (
                    <DocRow
                      key={doc.id}
                      doc={doc}
                      versionLabel={versionLabel(doc.version)}
                      selected={selected.has(doc.id)}
                      isAdmin={!!isAdmin}
                      isDeveloper={!!isDeveloper}
                      assignedToMe={!!meName && doc.assignee === meName}
                      onToggle={() => toggle(doc.id)}
                      onOpen={() => navigate(`/projects/${projectId}/documents/${doc.id}`)}
                      onCompare={() => navigate(`/projects/${projectId}/compare`)}
                      onDownload={() => downloadDoc(doc.id, doc.name)}
                      onAssign={() => toast.info('Assign reviewer', 'Open a document to assign reviewers.')}
                      onAssignToMe={() => selfAssign.mutate(doc.id)}
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
                  <p className="text-on-surface font-medium text-sm">No documents found</p>
                  <Text as="p" variant="caption" className="font-mono mt-1">
                    Try a different process, status, or search term.
                  </Text>
                </div>
              </div>
            )}
          </div>

          {/* ── Footer ── */}
          {!isLoading && filtered.length > 0 && (
            <div className="px-5 py-3.5 border-t border-outline-variant flex items-center justify-between bg-white">
              <Text as="p" variant="caption" className="font-mono">
                Showing {filtered.length} document{filtered.length !== 1 ? 's' : ''}
              </Text>
            </div>
          )}
        </Card>
        </div>
      </div>
    </div>
  )
}

/* ── Single row ── */
function DocRow({
  doc, versionLabel, selected, isAdmin, isDeveloper, assignedToMe,
  onToggle, onOpen, onCompare, onDownload, onAssign, onAssignToMe,
}: {
  doc: Document; versionLabel: string; selected: boolean
  isAdmin: boolean; isDeveloper: boolean; assignedToMe: boolean
  onToggle: () => void; onOpen: () => void; onCompare: () => void; onDownload: () => void
  onAssign: () => void; onAssignToMe: () => void
}) {
  const isUnchanged = statusBucket(doc.status) === 'unchanged'
  return (
    <tr
      className={cn('border-b border-outline-variant last:border-0 cursor-pointer transition-colors', selected && 'bg-surface-container-low')}
      onClick={onOpen}
    >
      <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          aria-label={`Select ${doc.name}`}
          checked={selected}
          onChange={onToggle}
          className="accent-secondary w-[15px] h-[15px] cursor-pointer"
        />
      </td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-surface-container-low border border-outline-variant flex items-center justify-center flex-shrink-0">
            <Icon name="article" size={15} className="text-on-surface-variant" />
          </div>
          <div>
            <p className="text-on-surface hover:text-secondary transition-colors font-mono text-body font-medium">{doc.name}</p>
            <Text as="p" variant="caption" className="font-mono mt-0.5">{doc.subtitle}</Text>
          </div>
        </div>
      </td>
      <td className="px-4 py-3.5"><ProcessBadge process={doc.process} /></td>
      <td className="px-4 py-3.5 font-mono text-caption text-on-surface-variant">{versionLabel}</td>
      <td className="px-4 py-3.5">
        {doc.assignee ? (
          <div className="flex items-center gap-2">
            <div
              className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0"
              // eslint-disable-next-line no-restricted-syntax -- assignee avatar colour is data-driven
              style={{ background: doc.assigneeColor }}
            >
              {/* eslint-disable-next-line no-restricted-syntax -- assignee avatar text colour is data-driven */}
              <span className="font-bold font-sans text-micro" style={{ color: doc.assigneeTextColor }}>{doc.assigneeInitials}</span>
            </div>
            <span className="text-on-surface truncate font-mono text-caption max-w-[100px]">{doc.assignee}</span>
          </div>
        ) : (
          <span className="text-outline text-xs">—</span>
        )}
      </td>
      <td className="px-4 py-3.5"><StatusBadge status={doc.status} /></td>
      <td className="px-4 py-3.5 font-mono text-caption text-outline">{doc.due}</td>
      <td className="px-4 py-3.5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-1">
          <button onClick={onOpen} title="View" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-secondary">
            <Icon name="open_in_new" size={15} />
          </button>
          <button onClick={onDownload} title="Download DOCX" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
            <Icon name="download" size={15} />
          </button>
          {isUnchanged ? (
            <span title="No changes from reference" className="p-1.5 flex items-center cursor-not-allowed text-outline-variant">
              <Icon name="compare_arrows" size={15} />
            </span>
          ) : (
            <button onClick={onCompare} title="Compare vs reference" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
              <Icon name="compare_arrows" size={15} />
            </button>
          )}
          {/* Role-aware assign: admin assigns a reviewer; a developer claims it */}
          {isAdmin ? (
            <button onClick={onAssign} title="Assign reviewer" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
              <Icon name="person_add" size={15} />
            </button>
          ) : isDeveloper ? (
            assignedToMe ? (
              <span title="Assigned to me" className="p-1.5 flex items-center text-[#00a572]">
                <Icon name="how_to_reg" size={15} />
              </span>
            ) : (
              <button onClick={onAssignToMe} title="Assign to me" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-secondary">
                <Icon name="person_add" size={15} />
              </button>
            )
          ) : null}
          <button title="More" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
            <Icon name="more_vert" size={15} />
          </button>
        </div>
      </td>
    </tr>
  )
}
