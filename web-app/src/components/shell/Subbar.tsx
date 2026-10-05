import { useState, useEffect, useRef, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useVersions, useCommits, useCommitsLastSync, useProjects } from '../../hooks/useProjects'
import { usePickerSelection } from '../../hooks/useProjectViewState'
import { useUIStore, type Selection } from '../../store/ui'
import { Icon, Skeleton, StatusBadge } from '../ui'
import { cn } from '../../lib/cn'
import { relativeTime } from '../../lib/format'
import { STATUS_META, approvalLabel, pageStateStatus } from '../../lib/reviewStatus'
import { describeVersionRun } from '../../lib/versionRun'
import { RenameProjectDialog } from './RenameProjectDialog'
import type { Version, Commit, PageState } from '../../types'

/* ─── Commit timeline dot colours (fill + border) ─── */
function commitDotClass(commit: Commit, isCurrent: boolean): string {
  const fill = commit.versionTag ? 'bg-[#00a572]' : isCurrent ? 'bg-secondary' : 'bg-white'
  const border = isCurrent ? 'border-secondary' : commit.versionTag ? 'border-[#00a572]' : 'border-outline-variant'
  return cn(fill, border)
}

/* ─── Subbar status chip: the version on screen, derived from its documents ─── */
// "In review · 3/6 approved" or "Approved" (REVIEW_APPROVE_DESIGN: a version is approved when
// every one of its documents is — never set by hand).
export function VersionStatusChip({ state, version }: { state: PageState; version?: Version }) {
  const key = pageStateStatus(state)
  const r = version?.review
  if ((key === 'in_review' || key === 'approved') && r && r.documents > 0) {
    const all = r.approved === r.documents
    return (
      <StatusBadge
        status={all ? 'approved' : 'in_review'}
        label={approvalLabel(r.approved, r.documents)}
        title={all
          ? `Every document is approved${r.approvedBy ? ` (last by ${r.approvedBy.name})` : ''}`
          : `${version.tag} is approved when every one of its ${r.documents} documents is`}
      />
    )
  }
  return <StatusBadge status={key} />
}

/* ─── Version row ─── */
function VersionRow({ version, isActive, onSelect }: { version: Version; isActive: boolean; onSelect: () => void }) {
  return (
    <button
      onClick={onSelect}
      className={cn(
        'w-full flex border-b border-outline-variant text-left transition-colors cursor-pointer',
        isActive ? 'bg-[#f5f8ff]' : 'hover:bg-[#f8f9fa]',
      )}
    >
      <div className={cn('w-[3px] flex-shrink-0', version.status === 'draft' ? 'bg-outline-variant' : STATUS_META[version.status].dot)} aria-hidden />
      <div className="flex-1 min-w-0 pt-[11px] pr-3 pb-2.5 pl-2.5">
        <div className="flex items-center justify-between gap-2 mb-[3px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-bold text-on-surface">{version.tag}</span>
            {version.status === 'in_review' && <StatusBadge status="in_review" size="sm" />}
          </div>
          {isActive && <Icon name="check" size={15} className="text-secondary flex-shrink-0" />}
        </div>
        <div className="text-caption text-on-surface-variant mb-1 leading-[1.4] truncate">{version.description}</div>
        {(() => {
          const made = describeVersionRun(version.run)
          return made ? <div className="font-mono text-label text-outline mb-1 truncate" title="How this version was made">{made}</div> : null
        })()}
        <div className="flex items-center gap-2">
          <span className="font-mono text-label text-outline bg-[#f3f4f6] px-[5px] py-px rounded-lg">{version.shortSha}</span>
          <span className="text-label text-outline">{version.date}</span>
          <VersionProgress version={version} />
        </div>
      </div>
    </button>
  )
}

/* "3 of 6 approved" while in review; "6 docs · by Alice" once approved (versions.html picker). */
function VersionProgress({ version }: { version: Version }) {
  const r = version.review
  if (!r || version.status === 'draft' || r.documents === 0) {
    return <span className="text-label text-outline">{version.docsCount} docs</span>
  }
  if (version.status === 'approved') {
    return <span className="text-label text-outline">{r.documents} docs{r.approvedBy ? ` · by ${r.approvedBy.name}` : ''}</span>
  }
  return <span className="text-label text-[#b45309]">{r.approved} of {r.documents} approved</span>
}

/* ─── Commit row (timeline) ─── */
function CommitRow({ commit, isCurrent, isLast, onSelect }: { commit: Commit; isCurrent: boolean; isLast: boolean; onSelect: () => void }) {
  return (
    <button
      onClick={onSelect}
      className={cn('w-full flex text-left px-3 cursor-pointer', isCurrent ? 'bg-[#f5f8ff]' : 'hover:bg-[#f8f9fa]')}
    >
      <div className="flex flex-col items-center flex-shrink-0 w-[18px] pt-3" aria-hidden>
        <div className={cn('w-[9px] h-[9px] rounded-full border-2 flex-shrink-0', commitDotClass(commit, isCurrent))} />
        {!isLast && <div className="w-0.5 flex-1 min-h-2.5 bg-[#e2e3e8] mt-[3px]" />}
      </div>
      <div className="flex-1 min-w-0 py-2.5 pl-2">
        <div className="flex items-center justify-between gap-1.5 mb-0.5">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-mono text-label font-semibold text-on-surface-variant bg-[#f3f4f6] px-[5px] py-px rounded-lg">{commit.shortSha}</span>
            {commit.versionTag && (
              <span className="inline-flex items-center gap-0.5 font-mono text-micro font-semibold text-[#00a572] bg-[#f0fdf9] border border-[#86efac] px-1.5 rounded-full">
                <Icon name="sell" size={10} />{commit.versionTag}
              </span>
            )}
            <StatusBadge status={pageStateStatus(commit.pageState)} size="sm" />
          </div>
          {isCurrent && <Icon name="check" size={14} className="text-secondary flex-shrink-0" />}
        </div>
        <div className="text-caption text-on-surface truncate max-w-[290px]">{commit.message}</div>
        <div className="text-label text-outline mt-px">{commit.author} · {commit.relativeTime}</div>
      </div>
    </button>
  )
}

/* ─── Commit/version picker ─── */
function CommitPicker({ selectedVersion, selectedCommit }: { selectedVersion?: Version; selectedCommit?: Commit }) {
  const { projectId } = useParams<{ projectId: string }>()
  const { data: versions, isLoading: versionsLoading } = useVersions(projectId ?? '')
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId ?? '')
  const { data: lastSyncedAt } = useCommitsLastSync(projectId ?? '')

  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'versions' | 'commits'>('versions')
  const [search, setSearch] = useState('')
  const wrapRef = useRef<HTMLDivElement>(null)

  // Selection is shared via the UI store so the detail page + status badge react
  // to it; default to the layout-supplied latest version / commit (also when the
  // picked version is gone, e.g. a cancelled run's draft).
  const selection = usePickerSelection(projectId ?? '')
  const setSelectedRef = useUIStore((s) => s.setSelectedRef)

  // Close on outside click
  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  // Resolve the active version/commit from the selection. With nothing
  // explicitly selected, default to the layout-supplied latest (prefer the
  // version, else the commit) so they stay mutually exclusive: the chip shows
  // the version tag by default and only falls back to "branch @ commit" when a
  // specific commit with no version is picked.
  const activeVersion = selection?.type === 'version'
    ? versions?.find((v) => v.id === selection.id)
    : !selection ? selectedVersion : undefined
  const activeCommit = selection?.type === 'commit'
    ? commits?.find((c) => c.sha === selection.sha)
    : (!selection && !selectedVersion) ? selectedCommit : undefined
  const chipVersionTag = activeVersion?.tag ?? activeCommit?.versionTag
  const chipBranch = activeCommit?.branch ?? activeVersion?.branch ?? 'main'
  const chipSha = activeCommit?.shortSha ?? activeVersion?.shortSha ?? ''
  const chipHasVersion = Boolean(chipVersionTag)

  const filteredCommits = (commits ?? []).filter((c) => {
    const q = search.trim().toLowerCase()
    return !q || c.shortSha.includes(q) || c.message.toLowerCase().includes(q) || c.author.toLowerCase().includes(q)
  })

  function select(sel: Selection) {
    if (projectId) setSelectedRef(projectId, sel)
    setOpen(false)
  }

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 border border-outline-variant rounded-lg hover:bg-surface-container transition-colors font-mono text-caption font-medium whitespace-nowrap"
        aria-haspopup="true"
        aria-expanded={open}
      >
        {activeVersion?.status === 'draft' ? (
          // Still being generated: a spinner, not the green tag of a finished version (mockup).
          <span className="animate-spin w-[11px] h-[11px] rounded-full border-[1.5px] border-secondary border-t-transparent flex-shrink-0" aria-label="Generating" />
        ) : (
          <Icon name={chipHasVersion ? 'sell' : 'alt_route'} size={13} fill={chipHasVersion} className="text-on-tertiary-container flex-shrink-0" />
        )}
        <span className="text-on-surface font-semibold">{chipVersionTag ?? `${chipBranch} @ ${chipSha}`}</span>
        <Icon name="expand_more" size={13} className={cn('text-on-surface-variant flex-shrink-0 transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1.5 bg-white border border-outline-variant rounded-xl overflow-hidden min-w-[380px] z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)]">
          {/* Tabs */}
          <div className="flex items-center border-b border-outline-variant px-3">
            <button
              onClick={() => setTab('versions')}
              className={cn('px-1 py-2.5 mr-5 -mb-px border-b-2 transition-colors font-mono text-xs font-medium', tab === 'versions' ? 'border-secondary text-secondary' : 'border-transparent text-on-surface-variant hover:text-on-surface')}
            >
              Versions
            </button>
            <button
              onClick={() => setTab('commits')}
              className={cn('px-1 py-2.5 -mb-px border-b-2 transition-colors font-mono text-xs font-medium', tab === 'commits' ? 'border-secondary text-secondary' : 'border-transparent text-on-surface-variant hover:text-on-surface')}
            >
              Commits
            </button>
          </div>

          {/* Versions panel */}
          {tab === 'versions' && (
            <div className="overflow-y-auto max-h-[280px]">
              {versionsLoading && !versions ? (
                <div className="p-3 space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
              ) : (versions ?? []).length === 0 ? (
                <div className="px-4 py-6 text-center text-xs text-outline">No versions yet</div>
              ) : (
                versions!.map((v) => (
                  <VersionRow
                    key={v.id ?? v.tag}
                    version={v}
                    isActive={!!activeVersion && (v.id ? v.id === activeVersion.id : v.sha === activeVersion.sha)}
                    onSelect={() => select(v.id ? { type: 'version', id: v.id } : { type: 'commit', sha: v.sha })}
                  />
                ))
              )}
            </div>
          )}

          {/* Commits panel */}
          {tab === 'commits' && (
            <div>
              <div className="px-3 py-2 border-b border-outline-variant">
                <div className="flex items-center gap-2 px-2 py-1.5 bg-surface-container-low border border-outline-variant rounded-lg">
                  <Icon name="search" size={15} className="text-on-surface-variant" />
                  <input
                    type="text"
                    placeholder="Search commits…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="flex-1 bg-transparent outline-none text-on-surface placeholder-outline font-mono text-caption"
                  />
                </div>
              </div>
              <div className="overflow-y-auto max-h-[240px]">
                {commitsLoading && !commits ? (
                  <div className="p-3 space-y-2">{Array.from({ length: 5 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
                ) : filteredCommits.length === 0 ? (
                  <div className="px-4 py-6 text-center text-xs text-outline">No commits match</div>
                ) : (
                  filteredCommits.map((c, i) => (
                    <CommitRow
                      key={c.sha}
                      commit={c}
                      isCurrent={!!activeCommit && c.sha === activeCommit.sha}
                      isLast={i === filteredCommits.length - 1}
                      onSelect={() => select({ type: 'commit', sha: c.sha })}
                    />
                  ))
                )}
              </div>
              {lastSyncedAt && (
                <div className="flex items-center gap-1 px-3 py-1.5 border-t border-outline-variant text-label text-outline">
                  <Icon name="sync" size={11} />
                  <span>Synced {relativeTime(lastSyncedAt)}</span>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/* ─── Project switcher dropdown ─── */
function ProjectSwitcher({ projectName, canRename }: { projectName: string; canRename?: boolean }) {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { data: projects, isLoading: projectsLoading } = useProjects()
  const [open, setOpen] = useState(false)
  const [renaming, setRenaming] = useState(false)
  const wrapRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDocClick)
    return () => document.removeEventListener('mousedown', onDocClick)
  }, [open])

  return (
    <div className="relative" ref={wrapRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1.5 px-2.5 py-[5px] border border-outline-variant rounded-md bg-white transition-colors hover:bg-surface-container-low hover:border-secondary font-mono text-xs"
        aria-haspopup="true"
        aria-expanded={open}
      >
        <Icon name="folder" size={14} fill className="text-secondary" />
        <span className="text-on-surface font-medium">{projectName}</span>
        <Icon name="expand_more" size={13} className={cn('text-on-surface-variant transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        // Capped: a project with no standard shows its repository, and a local path stretched the menu.
        <div className="absolute top-full left-0 mt-1.5 bg-white border border-outline-variant rounded-xl overflow-hidden min-w-[260px] w-max max-w-[min(400px,calc(100vw-32px))] z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)]">
          <div className="px-3 py-2 border-b border-outline-variant">
            <span className="text-on-surface-variant uppercase font-mono text-label font-bold tracking-[.08em]">Switch project</span>
          </div>
          <div className="overflow-y-auto max-h-[320px]">
            {projectsLoading && !projects ? (
              <div className="p-3 space-y-2">{Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-10" />)}</div>
            ) : (projects ?? []).length === 0 ? (
              <div className="p-4 text-xs text-outline">No projects</div>
            ) : (
              projects!.map((p) => {
                const active = p.id === projectId
                return (
                  <button
                    key={p.id}
                    onClick={() => { setOpen(false); if (!active) navigate(`/projects/${p.id}/overview`) }}
                    className={cn('w-full flex items-center gap-2.5 px-3 py-2.5 text-left transition-colors', active ? 'bg-surface-container-low' : 'hover:bg-[#f8f9fa]')}
                  >
                    <Icon name="folder" size={15} fill className="text-secondary flex-shrink-0" />
                    <div className="flex-1 min-w-0">
                      <div className="text-on-surface font-medium truncate text-body">{p.name}</div>
                      <div className="text-on-surface-variant truncate font-mono text-label">{p.standard || p.repoPath}</div>
                    </div>
                    {active && <Icon name="check" size={15} className="text-secondary flex-shrink-0" />}
                  </button>
                )
              })
            )}
          </div>
          {/* The project's admins rename it here: the menu is on every page of the project. */}
          {canRename && projectId && (
            <div className="border-t border-outline-variant">
              <button
                onClick={() => { setOpen(false); setRenaming(true) }}
                className="w-full flex items-center gap-2 px-3 py-2.5 text-left hover:bg-[#f8f9fa] transition-colors font-mono text-xs text-secondary"
              >
                <Icon name="edit" size={15} />Rename this project
              </button>
            </div>
          )}
        </div>
      )}
      {renaming && projectId && (
        <RenameProjectDialog projectId={projectId} name={projectName} onClose={() => setRenaming(false)} />
      )}
    </div>
  )
}

interface SubbarProps {
  projectName: string
  /** The user may rename the project (its admins): the project menu offers it. */
  canRename?: boolean
  selectedVersion?: Version
  selectedCommit?: Commit
  statusBadge?: ReactNode
  cta?: ReactNode
  /** Receives the element pages render their action into (see SubbarCta). */
  ctaSlotRef?: (el: HTMLDivElement | null) => void
}

export function Subbar({ projectName, canRename, selectedVersion, selectedCommit, statusBadge, cta, ctaSlotRef }: SubbarProps) {
  return (
    <div className="h-12 flex-shrink-0 flex items-center justify-between px-4 bg-white border-b border-outline-variant z-20">
      <div className="flex items-center gap-2">
        <ProjectSwitcher projectName={projectName} canRename={canRename} />

        {(selectedVersion ?? selectedCommit) && (
          <>
            <span className="text-outline-variant select-none" aria-hidden>·</span>
            <CommitPicker selectedVersion={selectedVersion} selectedCommit={selectedCommit} />
          </>
        )}

        {statusBadge && (
          <>
            <span className="text-outline-variant select-none" aria-hidden>·</span>
            {statusBadge}
          </>
        )}
      </div>

      <div ref={ctaSlotRef} className="flex items-center gap-1.5">{cta}</div>
    </div>
  )
}
