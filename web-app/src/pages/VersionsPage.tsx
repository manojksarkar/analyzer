import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useVersions, useCommits } from '../hooks/useProjects'
import { useCreateVersion } from '../hooks/useVersionMutations'
import { useCurrentJob } from '../hooks/useJobs'
import { Card, Icon, Skeleton, StatusBadge, Text, toast } from '../components/ui'
import { cn } from '../lib/cn'
import { formatDate } from '../lib/format'
import { STATUS_META, versionStatusKey } from '../lib/reviewStatus'
import { describeVersionRun } from '../lib/versionRun'
import { useUIStore } from '../store/ui'
import type { Commit, Version } from '../types'

// A version's status is derived from its documents (approved when every one is, A14): the
// filters read it, nobody sets it.
type Filter = 'all' | 'in_review' | 'approved'

export function VersionsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('all')

  const { data: project } = useProject(projectId ?? '')
  const { data: versions, isLoading: versionsLoading } = useVersions(projectId ?? '')
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId ?? '')
  const { data: job } = useCurrentJob(projectId ?? '')
  const runningVersionId = job && ['queued', 'running', 'paused'].includes(job.status) ? job.versionId : null

  const isAdmin = project?.userRole === 'admin'
  const createVersion = useCreateVersion(projectId ?? '')
  const setSelectedRef = useUIStore((s) => s.setSelectedRef)

  // Documents and Compare show the Subbar's selected version, so select THIS one first —
  // otherwise both buttons opened the latest version whichever row was clicked.
  function openVersion(v: Version, page: 'documents' | 'compare') {
    if (projectId && v.id) setSelectedRef(projectId, { type: 'version', id: v.id })
    navigate(`/projects/${projectId}/${page}`)
  }

  function tagCommit(c: Commit) {
    if (!isAdmin) { toast.info('Tag version', 'Only project admins can tag versions.'); return }
    const tag = window.prompt(`Tag a new version for commit ${c.shortSha}:`, '')
    if (tag && tag.trim()) createVersion.mutate({ tag: tag.trim(), commit_sha: c.sha, branch: c.branch })
  }

  const allVersions = versions ?? []
  const inReview = allVersions.filter((v) => v.status === 'in_review')
  const approved = allVersions.filter((v) => v.status === 'approved')

  const filtered = filter === 'in_review' ? inReview : filter === 'approved' ? approved : allVersions
  const untagged = commits?.filter((c) => !c.versionTag) ?? []

  const filterDefs: { key: Filter; label: string; count: number }[] = [
    { key: 'all',       label: 'All',       count: allVersions.length },
    { key: 'in_review', label: 'In review', count: inReview.length },
    { key: 'approved',  label: 'Approved',  count: approved.length },
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
                {versionsLoading ? 'Loading…' : `${allVersions.length} version${allVersions.length !== 1 ? 's' : ''}`} · {project?.name ?? '…'}
              </Text>
              <p className="flex items-center gap-1 mt-1 text-caption text-outline">
                <Icon name="info" size={13} />
                A version is Approved when every one of its documents is — never set by hand.
              </p>
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
                  running={!!v.id && v.id === runningVersionId}
                  onView={() => openVersion(v, 'documents')}
                  onCompare={() => openVersion(v, 'compare')} />
              ))
            )}
          </div>
        </Card>

        {/* ── Untagged commits card ── */}
        <Card className="overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <Text as="h2" variant="heading" className="text-on-surface">Untagged Commits</Text>
              {!commitsLoading && <span className="font-mono text-label font-bold bg-[#f3f4f6] text-on-surface-variant px-2 py-0.5 rounded-full">{untagged.length}</span>}
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
                    {/* Mockup: SHA chip + one truncated line of message, then "author · time". */}
                    <div className="flex items-center gap-2.5 mb-1 min-w-0">
                      <span className="font-mono text-label font-medium bg-[#f3f4f6] text-on-surface-variant px-1.5 py-px rounded flex-shrink-0">{c.shortSha}</span>
                      <Text as="p" variant="body" className="text-xs text-on-surface truncate" title={c.message}>{c.message}</Text>
                    </div>
                    <Text as="p" variant="caption" className="text-outline">{c.author} · {c.relativeTime}</Text>
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
function VersionRow({ v, isCurrent, last, running, onView, onCompare }: { v: Version; isCurrent: boolean; last: boolean; running: boolean; onView: () => void; onCompare: () => void }) {
  const status = versionStatusKey(v.status, running)
  // How it was made: web or command line, its scope, which documents (or the model only).
  const made = describeVersionRun(v.run)
  return (
    // The last row has no bottom border: the card's own edge closes it (it was doubled).
    <div className={cn('flex transition-colors hover:bg-[#f8f9ff]', !last && 'border-b border-outline-variant')}>
      {/* status accent bar */}
      <div className={cn('w-1 flex-shrink-0', v.status === 'draft' ? 'bg-outline-variant' : STATUS_META[status].dot)} aria-hidden />
      <div className="flex-1 px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap mb-1.5">
              <Text variant="title" className="font-mono font-bold text-on-surface">{v.tag}</Text>
              <StatusBadge status={status} size="sm" />
              {isCurrent && (
                <span className="uppercase font-mono text-micro font-bold bg-surface-container text-secondary border border-[#bfcfff] px-1.5 rounded-full tracking-[0.04em]">current</span>
              )}
            </div>
            <Text as="p" variant="body" className="text-on-surface-variant mb-2 leading-[1.5]">{v.description}</Text>
            <ReviewLine v={v} />
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className="font-mono text-label font-medium bg-[#f3f4f6] text-on-surface-variant px-1.5 py-px rounded">{v.shortSha}</span>
              <Text variant="caption" className="text-outline">{v.docsCount} docs</Text>
              <Text variant="caption" className="text-outline">·</Text>
              <Text variant="caption" className="text-outline">{v.date}</Text>
              {made && (
                <>
                  <Text variant="caption" className="text-outline">·</Text>
                  <Text variant="caption" className="font-mono text-on-surface-variant" title="How this version was made">{made}</Text>
                </>
              )}
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

/* How far a version's documents are: "N of M documents approved" with a bar while in review;
   who approved it, and when, once every document is (versions.html reviewLine). */
function ReviewLine({ v }: { v: Version }) {
  const r = v.review
  if (!r || v.status === 'draft' || r.documents === 0) return null
  if (v.status === 'approved') {
    return (
      <div className="flex items-center gap-1.5 flex-wrap mb-2.5">
        <Icon name="verified" size={14} fill className="text-[#00a572]" />
        <span className="text-xs text-on-surface">
          Approved{r.approvedBy ? <> by <b className="font-semibold">{r.approvedBy.name}</b></> : ''}
          {r.approvedAt ? ` · ${formatDate(r.approvedAt)}` : ''}
        </span>
        <span className="text-caption text-outline">· the last of {r.documents} document approvals</span>
      </div>
    )
  }
  const pct = Math.round((r.approved / r.documents) * 100)
  return (
    <div className="mb-2.5">
      <div className="flex items-center gap-2.5">
        <div className="w-[140px] h-1 rounded-full bg-[#fde7b0] overflow-hidden flex-shrink-0" title={`${pct}% of documents approved`}>
          {/* eslint-disable-next-line no-restricted-syntax -- the approved share is data-driven */}
          <span className="block h-full bg-[#00a572]" style={{ width: `${pct}%` }} />
        </div>
        <span className="text-xs text-on-surface"><b className="font-semibold">{r.approved} of {r.documents}</b> documents approved</span>
      </div>
      {r.carried > 0 && (
        <p className="text-caption text-outline mt-1">
          {r.carried} approval{r.carried === 1 ? '' : 's'} carried from an earlier version (content unchanged)
        </p>
      )}
    </div>
  )
}
