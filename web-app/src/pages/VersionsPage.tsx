import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useVersions, useCommits } from '../hooks/useProjects'
import { useCreateVersion } from '../hooks/useVersionMutations'
import { Card, Icon, Skeleton, Text, toast } from '../components/ui'
import { cn } from '../lib/cn'
import type { Commit, Version, VersionStatus } from '../types'

type Filter = 'all' | 'in_review' | 'complete'

function accentColor(s: VersionStatus): string {
  if (s === 'in_review') return '#f59e0b'
  if (s === 'approved' || s === 'complete') return '#00a572'
  return '#c4c6cd'
}

function StatusPill({ status }: { status: VersionStatus }) {
  if (status === 'in_review') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-mono text-label font-bold bg-[#fff8e6] text-[#b45309] border border-amber">
        <span className="inline-block w-1 h-1 rounded-full bg-amber" aria-hidden />In Review
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-mono text-label font-bold bg-[#f0fdf9] text-[#00a572] border border-[#86efac]">
      <span className="inline-block w-1 h-1 rounded-full bg-[#00a572]" aria-hidden />Approved
    </span>
  )
}

export function VersionsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('all')

  const { data: project } = useProject(projectId ?? '')
  const { data: versions, isLoading: versionsLoading } = useVersions(projectId ?? '')
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId ?? '')

  const isAdmin = project?.userRole === 'admin'
  const createVersion = useCreateVersion(projectId ?? '')

  function tagCommit(c: Commit) {
    if (!isAdmin) { toast.info('Tag version', 'Only project admins can tag versions.'); return }
    const tag = window.prompt(`Tag a new version for commit ${c.shortSha}:`, '')
    if (tag && tag.trim()) createVersion.mutate({ tag: tag.trim(), commit_sha: c.sha, branch: c.branch })
  }

  const allVersions = versions ?? []
  const inReview = allVersions.filter((v) => v.status === 'in_review')
  const complete = allVersions.filter((v) => v.status === 'complete' || v.status === 'approved')

  const filtered = filter === 'in_review' ? inReview : filter === 'complete' ? complete : allVersions
  const untagged = commits?.filter((c) => !c.versionTag) ?? []

  const filterDefs: { key: Filter; label: string; count: number }[] = [
    { key: 'all',       label: 'All',       count: allVersions.length },
    { key: 'in_review', label: 'In Review', count: inReview.length },
    { key: 'complete',  label: 'Complete',  count: complete.length },
  ]

  return (
    <div className="flex-1 overflow-y-auto bg-surface-container-low">
      <div className="p-6 max-w-[860px] mx-auto">

        {/* ── Versions card ── */}
        <Card className="overflow-hidden mb-5">
          <div className="px-5 py-4 border-b border-outline-variant flex items-center justify-between">
            <div>
              <Text as="h2" variant="heading" className="text-on-surface">Versions</Text>
              <Text as="p" variant="caption" className="font-mono mt-0.5">
                {allVersions.length} version{allVersions.length !== 1 ? 's' : ''} · {project?.name ?? '…'}
              </Text>
            </div>
            <div className="flex items-center gap-1.5">
              {filterDefs.map(({ key, label, count }) => {
                const active = filter === key
                return (
                  <button
                    key={key}
                    onClick={() => setFilter(key)}
                    className={cn(
                      'inline-flex items-center gap-1 transition-colors px-2.5 py-1 rounded-md font-mono text-caption font-semibold border',
                      active ? 'border-secondary bg-surface-container text-secondary' : 'border-transparent text-on-surface-variant',
                    )}
                  >
                    {label}
                    <span
                      className={cn(
                        'inline-flex items-center justify-center min-w-4 h-4 px-1 rounded-full text-label font-bold',
                        active ? 'bg-secondary text-white' : 'bg-surface-container text-secondary',
                      )}
                    >
                      {count}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Version rows */}
          <div>
            {versionsLoading ? (
              <div className="p-4 space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20" />)}</div>
            ) : filtered.length === 0 ? (
              <div className="py-14 flex flex-col items-center text-center gap-3">
                <div className="w-10 h-10 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
                  <Icon name="local_offer" className="text-on-surface-variant" />
                </div>
                <Text variant="mono" className="text-on-surface-variant">No versions match this filter</Text>
              </div>
            ) : (
              filtered.map((v, i, arr) => (
                <VersionRow key={v.tag} v={v} isCurrent={i === 0 && filter === 'all'} last={i === arr.length - 1}
                  onView={() => navigate(`/projects/${projectId}/documents`)}
                  onCompare={() => navigate(`/projects/${projectId}/compare`)} />
              ))
            )}
          </div>
        </Card>

        {/* ── Untagged commits card ── */}
        <Card className="overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Text as="h2" variant="heading" className="text-on-surface">Untagged Commits</Text>
              <span className="font-mono text-label font-bold bg-[#f3f4f6] text-on-surface-variant px-2 py-0.5 rounded-full">{untagged.length}</span>
            </div>
            <Text as="p" variant="caption" className="font-mono">Commits without a version tag</Text>
          </div>
          <div className="py-2">
            {commitsLoading ? (
              <div className="p-4 space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
            ) : untagged.length === 0 ? (
              <div className="px-5 py-6 text-xs text-outline">All commits have version tags.</div>
            ) : (
              untagged.map((c, i, arr) => (
                <button key={c.sha} onClick={() => tagCommit(c)} title="Tag this commit as a version" className="w-full text-left flex transition-colors hover:bg-surface-container-low px-4">
                  <div className="flex flex-col items-center w-5 flex-shrink-0 pt-3">
                    <div className="w-2 h-2 rounded-full bg-white border-2 border-outline-variant flex-shrink-0" aria-hidden />
                    {i < arr.length - 1 && <div className="w-0.5 flex-1 min-h-2.5 bg-[#e2e3e8] mt-[3px]" aria-hidden />}
                  </div>
                  <div className={cn('flex-1 min-w-0 pl-2.5 py-2.5', i < arr.length - 1 && 'border-b border-[#f3f4f6]')}>
                    <div className="flex items-center gap-2.5 mb-1">
                      <span className="font-mono text-label font-medium bg-[#f3f4f6] text-on-surface-variant px-1.5 py-px rounded-lg">{c.shortSha}</span>
                      <Text variant="caption" className="text-outline">{c.relativeTime}</Text>
                    </div>
                    <Text as="p" variant="body" className="text-on-surface leading-[1.4]">{c.message}</Text>
                    <Text as="p" variant="caption" className="text-outline mt-0.5">{c.author}</Text>
                  </div>
                </button>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}

/* ── Single version row ── */
function VersionRow({ v, isCurrent, onView, onCompare }: { v: Version; isCurrent: boolean; last: boolean; onView: () => void; onCompare: () => void }) {
  return (
    <div className="flex transition-colors hover:bg-[#f8f9ff] border-b border-outline-variant">
      {/* dynamic status accent bar */}
      {/* eslint-disable-next-line no-restricted-syntax -- accent colour is data-driven */}
      <div className="w-1 flex-shrink-0" style={{ background: accentColor(v.status) }} aria-hidden />
      <div className="flex-1 px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap mb-1.5">
              <Text variant="title" className="font-mono font-bold text-on-surface">{v.tag}</Text>
              <StatusPill status={v.status} />
              {isCurrent && (
                <span className="uppercase font-mono text-micro font-bold bg-surface-container text-secondary border border-[#bfcfff] px-1.5 rounded-full tracking-[0.04em]">current</span>
              )}
            </div>
            <Text as="p" variant="body" className="text-on-surface-variant mb-2.5 leading-[1.5]">{v.description}</Text>
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="font-mono text-label font-medium bg-[#f3f4f6] text-on-surface-variant px-1.5 py-px rounded-lg">{v.shortSha}</span>
              <Text variant="caption" className="text-outline">{v.docsCount} docs</Text>
              <Text variant="caption" className="text-outline">·</Text>
              <Text variant="caption" className="text-outline">{v.date}</Text>
            </div>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0 pt-0.5">
            <button onClick={onView} className="inline-flex items-center gap-1 transition-colors px-2.5 py-[5px] border border-secondary rounded-md font-mono text-label font-semibold text-white bg-secondary whitespace-nowrap">
              <Icon name="description" size={13} aria-hidden />
              View docs
            </button>
            <button onClick={onCompare} className="inline-flex items-center gap-1 transition-colors hover:border-secondary hover:text-secondary px-2.5 py-[5px] border border-outline-variant rounded-md font-mono text-label font-semibold text-on-surface-variant bg-white whitespace-nowrap">
              <Icon name="compare_arrows" size={13} aria-hidden />
              Compare
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
