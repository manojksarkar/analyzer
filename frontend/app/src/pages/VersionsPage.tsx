import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useVersions, useCommits } from '../hooks/useProjects'
import { Button, Badge, Skeleton } from '../components/ui'
import type { VersionStatus } from '../types'

type Filter = 'All' | 'In Review' | 'Complete'

const ACCENT_COLOR: Record<VersionStatus, string> = {
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

  const allVersions  = versions ?? []
  const inReview     = allVersions.filter((v) => v.status === 'in_review')
  const complete     = allVersions.filter((v) => v.status === 'complete')

  const filtered = filter === 'In Review' ? inReview
                 : filter === 'Complete'  ? complete
                 : allVersions

  const untaggedCommits = commits?.filter((c) => !c.versionTag) ?? []

  const filterDefs: { label: Filter; count: number }[] = [
    { label: 'All',       count: allVersions.length },
    { label: 'In Review', count: inReview.length },
    { label: 'Complete',  count: complete.length },
  ]

  return (
    <div className="p-6">
      {/* Filter buttons with count badges */}
      <div className="flex items-center gap-2 mb-5" role="tablist" aria-label="Filter versions">
        {filterDefs.map(({ label, count }) => {
          const active = filter === label
          return (
            <button
              key={label}
              role="tab"
              aria-selected={active}
              onClick={() => setFilter(label)}
              className="flex items-center gap-1.5 px-3 h-8 rounded-full text-xs font-semibold transition-colors"
              style={{
                background: active ? '#e5eeff' : '#f3f4f6',
                color: active ? '#0058be' : '#44474c',
                border: active ? '1px solid #0058be' : '1px solid transparent',
              }}
            >
              {label}
              <span
                className="flex items-center justify-center min-w-[18px] h-[18px] rounded-full px-1 text-[10px] font-bold"
                style={{
                  background: active ? '#0058be' : '#c4c6cd',
                  color: active ? '#fff' : '#44474c',
                }}
              >
                {count}
              </span>
            </button>
          )
        })}
      </div>

      {/* Tagged versions — flat ver-row layout */}
      <div className="bg-white border border-outline-variant rounded-xl overflow-hidden mb-8">
        {versionsLoading
          ? Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-20 border-b border-outline-variant" />)
          : filtered.length === 0 ? (
              <div className="flex items-center justify-center h-20 text-sm text-on-surface-variant">
                No versions match this filter.
              </div>
            )
          : filtered.map((v, idx, arr) => (
              <article
                key={v.tag}
                className="flex"
                style={{ borderBottom: idx < arr.length - 1 ? '1px solid #c4c6cd' : 'none' }}
              >
                {/* 4px accent bar */}
                <div
                  className="w-1 flex-shrink-0"
                  style={{ background: ACCENT_COLOR[v.status] }}
                  aria-hidden
                />

                <div className="flex-1 flex items-center gap-4 px-5 py-4 min-w-0">
                  {/* Tag + status pill */}
                  <div className="flex items-center gap-2.5 flex-shrink-0">
                    <span className="material-symbols-outlined sym-fill text-on-tertiary-container" style={{ fontSize: 16 }} aria-hidden>sell</span>
                    <span className="font-mono text-sm font-bold text-on-surface">{v.tag}</span>
                    {v.status === 'in_review' && <Badge variant="warning">In Review</Badge>}
                  </div>

                  {/* Description */}
                  <p className="flex-1 text-sm text-on-surface-variant truncate hidden md:block">{v.description}</p>

                  {/* Meta */}
                  <div className="flex items-center gap-4 flex-shrink-0">
                    <span
                      className="font-mono text-[10px] px-1.5 py-0.5 rounded"
                      style={{ background: '#f3f4f6', color: '#44474c', borderRadius: 4 }}
                    >
                      {v.shortSha}
                    </span>
                    <span className="text-xs text-on-surface-variant whitespace-nowrap">{v.docsCount} docs</span>
                    <span className="text-xs text-on-surface-variant whitespace-nowrap">{v.date}</span>
                  </div>

                  {/* Action buttons */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => navigate(`/projects/${projectId}/documents`)}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>description</span>
                      View
                    </Button>
                    <Button
                      size="sm"
                      onClick={() => navigate(`/projects/${projectId}/compare`)}
                    >
                      <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>compare_arrows</span>
                      Compare
                    </Button>
                  </div>
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
                      <span
                        className="font-mono text-[10px] px-2 py-0.5"
                        style={{ background: '#f3f4f6', color: '#44474c', borderRadius: 4 }}
                      >
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
