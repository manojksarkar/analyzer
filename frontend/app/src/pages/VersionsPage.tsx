import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useVersions, useCommits } from '../hooks/useProjects'
import { Button, Badge, Skeleton } from '../components/ui'
import type { VersionStatus } from '../types'

type Filter = 'All' | 'In Review' | 'Complete'

const STATUS_BAR: Record<VersionStatus, string> = {
  complete:  '#00a572',
  in_review: '#f59e0b',
  approved:  '#0058be',
}

export function VersionsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [filter, setFilter] = useState<Filter>('All')

  const { data: versions, isLoading: versionsLoading } = useVersions(projectId ?? '')
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId ?? '')

  const filtered = versions?.filter((v) => {
    if (filter === 'In Review') return v.status === 'in_review'
    if (filter === 'Complete')  return v.status === 'complete'
    return true
  }) ?? []

  const untaggedCommits = commits?.filter((c) => !c.versionTag) ?? []

  return (
    <div className="p-6">
      {/* Filter tabs */}
      <div className="flex items-center gap-1 mb-5" role="tablist" aria-label="Filter versions">
        {(['All', 'In Review', 'Complete'] as Filter[]).map((f) => (
          <button
            key={f}
            role="tab"
            aria-selected={filter === f}
            onClick={() => setFilter(f)}
            className={`px-3 h-8 rounded-lg text-xs font-semibold transition-colors ${
              filter === f ? 'bg-secondary text-white shadow-sm' : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Tagged versions */}
      <div className="space-y-3 mb-8">
        {versionsLoading
          ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-24 rounded-xl" />)
          : filtered.map((v) => (
              <article key={v.tag} className="bg-white border border-outline-variant rounded-xl p-5 flex gap-4">
                <div
                  className="w-1 self-stretch rounded-full flex-shrink-0"
                  style={{ background: STATUS_BAR[v.status] }}
                  aria-hidden
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-3 mb-1.5">
                    <span className="material-symbols-outlined sym-fill text-on-tertiary-container" style={{ fontSize: 16 }} aria-hidden>sell</span>
                    <span className="font-mono text-sm font-bold text-on-surface">{v.tag}</span>
                    {v.status === 'in_review' && <Badge variant="warning">In Review</Badge>}
                    {v.status === 'complete'  && <Badge variant="success">Complete</Badge>}
                  </div>
                  <p className="text-sm text-on-surface-variant mb-3 leading-relaxed">{v.description}</p>
                  <div className="flex items-center gap-4">
                    <span className="font-mono text-[10px] bg-surface-container px-2 py-0.5 rounded border border-outline-variant text-on-surface-variant">
                      {v.shortSha}
                    </span>
                    <span className="text-xs text-on-surface-variant">{v.docsCount} docs</span>
                    <span className="text-xs text-on-surface-variant">{v.date}</span>
                  </div>
                </div>
                <div className="flex items-center gap-2 flex-shrink-0">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => navigate(`/projects/${projectId}/documents`)}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>description</span>
                    Docs
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => navigate(`/projects/${projectId}/compare`)}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>compare_arrows</span>
                    Compare
                  </Button>
                </div>
              </article>
            ))}
      </div>

      {/* Untagged commits */}
      {filter === 'All' && (
        <section aria-label="Untagged commits">
          <h3 className="text-xs font-mono text-on-surface-variant uppercase tracking-[0.08em] mb-4">Untagged Commits</h3>
          {commitsLoading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-14 rounded-xl" />)}
            </div>
          ) : (
            <div>
              {untaggedCommits.map((commit, i, arr) => (
                <div key={commit.sha} className="flex gap-5">
                  <div className="flex flex-col items-center flex-shrink-0">
                    <div className="w-2.5 h-2.5 rounded-full border-2 border-outline-variant bg-white mt-2.5" aria-hidden />
                    {i < arr.length - 1 && <div className="w-px flex-1 bg-outline-variant my-1" aria-hidden />}
                  </div>
                  <div className="flex-1 pb-5">
                    <div className="flex items-center gap-3 mb-1">
                      <span className="font-mono text-[10px] bg-surface-container border border-outline-variant px-2 py-0.5 rounded text-on-surface-variant">
                        {commit.shortSha}
                      </span>
                      <span className="text-xs text-on-surface-variant">{commit.relativeTime}</span>
                    </div>
                    <p className="text-sm text-on-surface leading-relaxed">{commit.message}</p>
                    <p className="text-xs text-on-surface-variant mt-0.5">{commit.author}</p>
                  </div>
                </div>
              ))}
              {untaggedCommits.length === 0 && (
                <p className="text-sm text-on-surface-variant">All commits are tagged.</p>
              )}
            </div>
          )}
        </section>
      )}
    </div>
  )
}
