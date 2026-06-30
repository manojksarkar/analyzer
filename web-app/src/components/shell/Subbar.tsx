import { useState, useEffect, useRef, type ReactNode } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useVersions, useCommits, useCommitsLastSync, useProjects } from '../../hooks/useProjects'
import { useUIStore, type Selection } from '../../store/ui'
import { Icon, Skeleton } from '../ui'
import { cn } from '../../lib/cn'
import { relativeTime } from '../../lib/format'
import type { Version, Commit, VersionStatus, PageState } from '../../types'

/* ─── Version-status accent (left stripe) ─── */
function versionAccentClass(status: VersionStatus): string {
  if (status === 'approved' || status === 'complete') return 'bg-[#00a572]'
  if (status === 'in_review') return 'bg-amber'
  return 'bg-outline-variant'
}

/* ─── Commit timeline dot colours (fill + border) ─── */
function commitDotClass(commit: Commit, isCurrent: boolean): string {
  const fill = commit.versionTag ? 'bg-[#00a572]' : isCurrent ? 'bg-secondary' : 'bg-white'
  const border = isCurrent ? 'border-secondary' : commit.versionTag ? 'border-[#00a572]' : 'border-outline-variant'
  return cn(fill, border)
}

/* ─── Page-state badge for commit rows ─── */
const STATE_MAP: Record<PageState, { icon: string; text: string; cls: string } | null> = {
  never:     { icon: 'radio_button_unchecked', text: 'Not Run',   cls: 'bg-[#f3f4f6] text-outline border-[#e2e3e8]' },
  running:   { icon: 'progress_activity',       text: 'Running',   cls: 'bg-surface-container text-secondary border-[#9cc3ff]' },
  in_review: { icon: 'rate_review',             text: 'In Review', cls: 'bg-[#fff8e6] text-[#b45309] border-amber' },
  complete:  { icon: 'check_circle',            text: 'Complete',  cls: 'bg-[#f0fdf9] text-[#00a572] border-[#86efac]' },
  stale:     { icon: 'warning',                 text: 'Stale',     cls: 'bg-[#fffbeb] text-[#d97706] border-amber' },
}

/* ─── Subbar status badge (matches project-detail.html updateStatusBadge) ─── */
const STATUS_BADGE: Record<PageState, { icon: string; text: string; cls: string }> = {
  never:     { icon: 'radio_button_unchecked', text: 'Not Run',   cls: 'bg-[#f3f4f6] text-outline border-[#e2e3e8]' },
  running:   { icon: 'sync',                    text: 'Running',   cls: 'bg-surface-container text-secondary border-[#bfcfff]' },
  in_review: { icon: 'rate_review',             text: 'In Review', cls: 'bg-[#fff8e6] text-[#b45309] border-amber' },
  complete:  { icon: 'check_circle',            text: 'Complete',  cls: 'bg-[#f0fdf9] text-[#00a572] border-[#86efac]' },
  stale:     { icon: 'warning',                 text: 'Stale',     cls: 'bg-[#fffbeb] text-[#d97706] border-amber' },
}

export function StatusBadge({ state }: { state: PageState }) {
  const c = STATUS_BADGE[state] ?? STATUS_BADGE.never
  return (
    <span className={cn('inline-flex items-center gap-1 font-mono text-label font-bold px-2 py-0.5 rounded-full whitespace-nowrap border', c.cls)}>
      <Icon name={c.icon} size={11} fill />
      {c.text}
    </span>
  )
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
      <div className={cn('w-[3px] flex-shrink-0', versionAccentClass(version.status))} aria-hidden />
      <div className="flex-1 min-w-0 pt-[11px] pr-3 pb-2.5 pl-2.5">
        <div className="flex items-center justify-between gap-2 mb-[3px]">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-xs font-bold text-on-surface">{version.tag}</span>
            {version.status === 'in_review' && (
              <span className="inline-flex items-center gap-1 font-mono text-[8px] font-bold bg-[#fff8e6] text-[#b45309] border border-amber px-1.5 rounded-full uppercase tracking-[0.04em]">
                <span className="inline-block w-1 h-1 rounded-full bg-amber" aria-hidden />
                In Review
              </span>
            )}
          </div>
          {isActive && <Icon name="check" size={15} className="text-secondary flex-shrink-0" />}
        </div>
        <div className="text-caption text-on-surface-variant mb-1 leading-[1.4] truncate">{version.description}</div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-label text-outline bg-[#f3f4f6] px-[5px] py-px rounded-lg">{version.shortSha}</span>
          <span className="text-label text-outline">{version.date}</span>
          <span className="text-label text-outline">{version.docsCount} docs</span>
        </div>
      </div>
    </button>
  )
}

/* ─── Commit row (timeline) ─── */
function CommitRow({ commit, isCurrent, isLast, onSelect }: { commit: Commit; isCurrent: boolean; isLast: boolean; onSelect: () => void }) {
  const sm = STATE_MAP[commit.pageState]
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
            {sm && (
              <span className={cn('inline-flex items-center gap-0.5 font-mono text-[8px] font-bold px-[5px] rounded-full whitespace-nowrap border', sm.cls)}>
                <Icon name={sm.icon} size={9} fill />{sm.text}
              </span>
            )}
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
  // to it; default to the layout-supplied latest version / commit.
  const selection = useUIStore((s) => (projectId ? s.selectedRef[projectId] : undefined))
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
        <Icon name={chipHasVersion ? 'sell' : 'alt_route'} size={13} fill={chipHasVersion} className="text-on-tertiary-container flex-shrink-0" />
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
function ProjectSwitcher({ projectName }: { projectName: string }) {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const { data: projects, isLoading: projectsLoading } = useProjects()
  const [open, setOpen] = useState(false)
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
        <div className="absolute top-full left-0 mt-1.5 bg-white border border-outline-variant rounded-xl overflow-hidden min-w-[260px] z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)]">
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
        </div>
      )}
    </div>
  )
}

interface SubbarProps {
  projectName: string
  selectedVersion?: Version
  selectedCommit?: Commit
  statusBadge?: ReactNode
  cta?: ReactNode
}

export function Subbar({ projectName, selectedVersion, selectedCommit, statusBadge, cta }: SubbarProps) {
  return (
    <div className="h-12 flex-shrink-0 flex items-center justify-between px-4 bg-white border-b border-outline-variant z-20">
      <div className="flex items-center gap-2">
        <ProjectSwitcher projectName={projectName} />

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

      {cta && <div className="flex items-center gap-1.5">{cta}</div>}
    </div>
  )
}
