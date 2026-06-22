import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useVersions, useCommits } from '../hooks/useProjects'
import { Skeleton } from '../components/ui'
import type { Version, VersionStatus } from '../types'

type Filter = 'all' | 'in_review' | 'complete'

function accentColor(s: VersionStatus): string {
  if (s === 'in_review') return '#f59e0b'
  if (s === 'approved' || s === 'complete') return '#00a572'
  return '#c4c6cd'
}

function StatusPill({ status }: { status: VersionStatus }) {
  if (status === 'in_review') {
    return (
      <span className="inline-flex items-center gap-1.5" style={{ padding: '2px 8px', borderRadius: 99, fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700, background: '#fff8e6', color: '#b45309', border: '1px solid #f59e0b' }}>
        <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#f59e0b', display: 'inline-block' }} aria-hidden />In Review
      </span>
    )
  }
  return (
    <span className="inline-flex items-center gap-1.5" style={{ padding: '2px 8px', borderRadius: 99, fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700, background: '#f0fdf9', color: '#00a572', border: '1px solid #86efac' }}>
      <span style={{ width: 4, height: 4, borderRadius: '50%', background: '#00a572', display: 'inline-block' }} aria-hidden />Approved
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
    <div className="flex-1 overflow-y-auto" style={{ background: '#eff4ff' }}>
      <div className="p-6" style={{ maxWidth: 860, margin: '0 auto' }}>

        {/* ── Versions card ── */}
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden mb-5">
          <div className="px-5 py-4 border-b border-outline-variant flex items-center justify-between">
            <div>
              <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Versions</h2>
              <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                {allVersions.length} version{allVersions.length !== 1 ? 's' : ''} · {project?.name ?? '…'}
              </p>
            </div>
            <div className="flex items-center gap-1.5">
              {filterDefs.map(({ key, label, count }) => {
                const active = filter === key
                return (
                  <button
                    key={key}
                    onClick={() => setFilter(key)}
                    className="inline-flex items-center gap-1 transition-colors"
                    style={{
                      padding: '4px 10px', borderRadius: 6, fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 600,
                      border: active ? '1px solid #0058be' : '1px solid transparent',
                      background: active ? '#e5eeff' : 'transparent',
                      color: active ? '#0058be' : '#44474c',
                    }}
                  >
                    {label}
                    <span
                      className="inline-flex items-center justify-center"
                      style={{ minWidth: 16, height: 16, padding: '0 4px', borderRadius: 99, fontSize: 10, fontWeight: 700, background: active ? '#0058be' : '#e5eeff', color: active ? '#fff' : '#0058be' }}
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
                  <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 20 }} aria-hidden>local_offer</span>
                </div>
                <p className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>No versions match this filter</p>
              </div>
            ) : (
              filtered.map((v, i, arr) => (
                <VersionRow key={v.tag} v={v} isCurrent={i === 0 && filter === 'all'} last={i === arr.length - 1}
                  onView={() => navigate(`/projects/${projectId}/documents`)}
                  onCompare={() => navigate(`/projects/${projectId}/compare`)} />
              ))
            )}
          </div>
        </div>

        {/* ── Untagged commits card ── */}
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Untagged Commits</h2>
              <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700, background: '#f3f4f6', color: '#44474c', padding: '2px 8px', borderRadius: 99 }}>{untagged.length}</span>
            </div>
            <p className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>Commits without a version tag</p>
          </div>
          <div className="py-2">
            {commitsLoading ? (
              <div className="p-4 space-y-3">{Array.from({ length: 3 }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>
            ) : untagged.length === 0 ? (
              <div style={{ padding: '24px 20px', fontSize: 12, color: '#74777d' }}>All commits have version tags.</div>
            ) : (
              untagged.map((c, i, arr) => (
                <button key={c.sha} className="commit-row w-full text-left flex transition-colors hover:bg-surface-container-low" style={{ padding: '0 16px' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', width: 20, flexShrink: 0, paddingTop: 12 }}>
                    <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#fff', border: '2px solid #c4c6cd', flexShrink: 0 }} aria-hidden />
                    {i < arr.length - 1 && <div style={{ width: 2, flex: 1, minHeight: 10, background: '#e2e3e8', marginTop: 3 }} aria-hidden />}
                  </div>
                  <div style={{ flex: 1, minWidth: 0, padding: '10px 0 10px 10px', borderBottom: i < arr.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
                    <div className="flex items-center gap-2.5 mb-1">
                      <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 500, background: '#f3f4f6', color: '#44474c', padding: '1px 6px', borderRadius: 4 }}>{c.shortSha}</span>
                      <span style={{ fontSize: 11, color: '#74777d' }}>{c.relativeTime}</span>
                    </div>
                    <p className="text-on-surface" style={{ fontSize: 13, lineHeight: 1.4 }}>{c.message}</p>
                    <p className="text-on-surface-variant mt-0.5" style={{ fontSize: 11 }}>{c.author}</p>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Single version row ── */
function VersionRow({ v, isCurrent, onView, onCompare }: { v: Version; isCurrent: boolean; last: boolean; onView: () => void; onCompare: () => void }) {
  return (
    <div className="flex transition-colors hover:bg-[#f8f9ff]" style={{ borderBottom: '1px solid #c4c6cd' }}>
      <div style={{ width: 4, flexShrink: 0, background: accentColor(v.status) }} aria-hidden />
      <div className="flex-1 px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2.5 flex-wrap mb-1.5">
              <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 15, fontWeight: 700, color: '#0b1c30' }}>{v.tag}</span>
              <StatusPill status={v.status} />
              {isCurrent && (
                <span className="uppercase" style={{ fontFamily: "'JetBrains Mono'", fontSize: 9, fontWeight: 700, background: '#e5eeff', color: '#0058be', border: '1px solid #bfcfff', padding: '0 6px', borderRadius: 99, letterSpacing: '0.04em' }}>current</span>
              )}
            </div>
            <p style={{ fontSize: 13, color: '#44474c', marginBottom: 10, lineHeight: 1.5 }}>{v.description}</p>
            <div className="flex items-center gap-2.5 flex-wrap">
              <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 500, background: '#f3f4f6', color: '#44474c', padding: '1px 6px', borderRadius: 4 }}>{v.shortSha}</span>
              <span style={{ fontSize: 11, color: '#74777d' }}>{v.docsCount} docs</span>
              <span style={{ fontSize: 11, color: '#74777d' }}>·</span>
              <span style={{ fontSize: 11, color: '#74777d' }}>{v.date}</span>
            </div>
          </div>
          <div className="flex items-center gap-1.5 flex-shrink-0 pt-0.5">
            <button onClick={onView} className="inline-flex items-center gap-1 transition-colors" style={{ padding: '5px 10px', border: '1px solid #0058be', borderRadius: 6, fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 600, color: '#fff', background: '#0058be', whiteSpace: 'nowrap' }}>
              <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>description</span>
              View docs
            </button>
            <button onClick={onCompare} className="inline-flex items-center gap-1 transition-colors hover:border-secondary hover:text-secondary" style={{ padding: '5px 10px', border: '1px solid #c4c6cd', borderRadius: 6, fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 600, color: '#44474c', background: '#fff', whiteSpace: 'nowrap' }}>
              <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>compare_arrows</span>
              Compare
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
