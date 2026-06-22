import { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useDocuments, useTeam } from '../hooks/useProjects'
import { useUIStore } from '../store/ui'
import { Button, Badge, RoleBadge, ProcessBadge, TableSkeleton } from '../components/ui'
import type { PageState, DocStatus, TeamMember } from '../types'

/* ─── Doc status config ─── */
const STATUS_CONFIG: Record<DocStatus, { label: string; variant: 'warning' | 'success' | 'primary' | 'default' }> = {
  in_review: { label: 'In Review', variant: 'warning' },
  approved:  { label: 'Approved',  variant: 'success' },
  complete:  { label: 'Complete',  variant: 'success' },
  draft:     { label: 'Draft',     variant: 'default' },
  unchanged: { label: 'Unchanged', variant: 'default' },
}

/* ─── KPI card ─── */
function KpiCard({ label, value, sub, icon, color }: { label: string; value: string; sub?: string; icon: string; color: string }) {
  return (
    <div className="bg-white border border-outline-variant rounded-xl p-5 hover:shadow-sm transition-shadow">
      <div className="flex items-center justify-between mb-3">
        <span
          className="text-on-surface-variant uppercase"
          style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 500, letterSpacing: '0.07em' }}
        >
          {label}
        </span>
        <span className="material-symbols-outlined" style={{ fontSize: 18, color }} aria-hidden>{icon}</span>
      </div>
      <p className="font-bold text-on-surface" style={{ fontSize: 28 }}>{value}</p>
      {sub && <p className="text-on-surface-variant mt-1" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{sub}</p>}
    </div>
  )
}

/* ─── Team member row ─── */
function TeamRow({ member }: { member: TeamMember }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-container-low transition-colors">
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
        style={{ background: member.avatarColor, color: member.avatarTextColor }}
        aria-hidden
      >
        <span style={{ fontFamily: 'Inter', fontSize: 10, fontWeight: 700 }}>{member.initials}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-on-surface truncate" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}>
          {member.name}
        </p>
      </div>
      <RoleBadge role={member.role} />
    </div>
  )
}

/* ─── Phase step (running panel) ─── */
type PhaseStatus = 'done' | 'active' | 'pending'
function PhaseStep({ n, label, status, time }: { n: number; label: string; status: PhaseStatus; time: string }) {
  const timeColor = status === 'done' ? '#00a572' : status === 'active' ? '#0058be' : '#c4c6cd'
  return (
    <div className="flex flex-col items-center text-center" style={{ minWidth: 105 }}>
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
        style={{ background: status === 'done' ? '#00a572' : status === 'active' ? '#0058be' : '#e5eeff' }}
      >
        {status === 'done' ? (
          <span className="material-symbols-outlined text-white sym-fill" style={{ fontSize: 14 }} aria-hidden>check</span>
        ) : status === 'active' ? (
          <div className="animate-spin" style={{ width: 14, height: 14, border: '2px solid rgba(255,255,255,.35)', borderTopColor: '#fff', borderRadius: '9999px' }} />
        ) : (
          <span style={{ fontSize: 13, fontWeight: 600, color: '#74777d' }}>{n}</span>
        )}
      </div>
      <p className="mt-1.5 font-semibold" style={{ fontSize: 11, color: status === 'pending' ? '#74777d' : '#0b1c30' }}>Phase {n}</p>
      <p className="text-on-surface-variant" style={{ fontSize: 10 }}>{label}</p>
      <p className="mt-0.5" style={{ fontSize: 10, color: timeColor, fontFamily: "'JetBrains Mono'" }}>{time}</p>
    </div>
  )
}

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const roleView = useUIStore((s) => s.roleView)
  const isAdmin = roleView === 'admin'

  const { data: project } = useProject(projectId ?? '')
  const { data: documents, isLoading: docsLoading } = useDocuments(projectId ?? '')
  const { data: team, isLoading: teamLoading } = useTeam(projectId ?? '')

  // State driven by the project's own pageState; mutable so Run/Re-run can switch to "running"
  const [pageState, setPageState] = useState<PageState>('in_review')
  useEffect(() => {
    if (project?.pageState) setPageState(project.pageState)
  }, [project?.pageState])

  const previewDocs  = documents?.slice(0, 6) ?? []
  const reviewQueue  = documents?.filter((d) => d.status === 'in_review') ?? []
  const unassigned   = documents?.filter((d) => !d.assignee) ?? []

  const showContent = ['in_review', 'complete', 'stale'].includes(pageState)

  return (
    <div className="flex-1 overflow-y-auto bg-background">
      <div className="px-6 py-6" style={{ maxWidth: 1280, margin: '0 auto' }}>

        {/* ══ EMPTY STATE ══ */}
        {pageState === 'never' && (
          <div className="mb-7 rounded-xl border border-outline-variant bg-white px-8 py-10 flex flex-col items-center text-center gap-5">
            <div className="w-14 h-14 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
              <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 28 }} aria-hidden>auto_awesome</span>
            </div>
            <div>
              <h3 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>No documents generated yet</h3>
              <p className="text-on-surface-variant mt-2" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, maxWidth: 340 }}>
                Run analysis on <strong>main @ abc1234</strong> to generate ASPICE-compliant documents for all 5 processes.
              </p>
            </div>
            <button
              onClick={() => setPageState('running')}
              className="flex items-center gap-2 px-5 py-2.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-xl transition-colors"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 700, letterSpacing: '0.04em' }}
            >
              <span className="material-symbols-outlined sym-fill" style={{ fontSize: 16 }} aria-hidden>play_circle</span>
              RUN ANALYSIS
            </button>
          </div>
        )}

        {/* ══ RUNNING STATE ══ */}
        {pageState === 'running' && (
          <div className="mb-7 rounded-xl overflow-hidden border border-outline-variant">
            {/* Dark header */}
            <div className="px-5 py-4 flex items-center justify-between" style={{ background: '#041627' }}>
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0" style={{ border: '2px solid #0058be', borderTopColor: 'transparent' }}>
                  <div className="animate-spin w-full h-full rounded-full" style={{ border: '2px solid #0058be', borderTopColor: 'transparent', borderRadius: '9999px' }} />
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <p className="text-white font-semibold" style={{ fontFamily: 'Inter', fontSize: 14 }}>Analysis Running</p>
                    <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 9, fontWeight: 700, background: '#0058be', color: '#fff', padding: '1px 7px', borderRadius: 3, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Live</span>
                  </div>
                  <div className="flex items-center gap-2 mt-0.5" style={{ color: '#8192a7' }}>
                    <span className="material-symbols-outlined" style={{ fontSize: 12 }} aria-hidden>source</span>
                    <p style={{ fontSize: 11, fontFamily: "'JetBrains Mono'" }}>Branch <span style={{ color: '#4d9fff' }}>main</span></p>
                    <span style={{ color: '#1e3045' }}>·</span>
                    <p style={{ fontSize: 11, fontFamily: "'JetBrains Mono'" }}>Commit <span style={{ color: '#4d9fff' }}>abc1234</span></p>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-5">
                <div className="text-right">
                  <p style={{ fontSize: 10, fontFamily: "'JetBrains Mono'", color: '#44474c', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Started</p>
                  <p style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, color: '#8192a7' }}>14:32</p>
                </div>
                <div className="text-right">
                  <p style={{ fontSize: 10, fontFamily: "'JetBrains Mono'", color: '#44474c', textTransform: 'uppercase', letterSpacing: '0.08em' }}>Elapsed</p>
                  <p style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, color: '#ffffff' }}>00:12:47</p>
                </div>
                <button
                  onClick={() => setPageState(project?.pageState ?? 'in_review')}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors"
                  style={{ border: '1px solid #4d2020', color: '#ff7070', fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500 }}
                >
                  <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>stop_circle</span>
                  Cancel Job
                </button>
              </div>
            </div>

            {/* Phase steps */}
            <div className="bg-white px-6 pt-5 pb-3">
              <div className="flex items-start">
                <PhaseStep n={1} label="Parse C++"     status="done"    time="Done · 3m 12s" />
                <div className="flex-1 mt-[14px]" style={{ height: 2, background: '#00a572', borderRadius: 9999, margin: '14px 6px 0' }} />
                <PhaseStep n={2} label="Derive Model"  status="active"  time="Running..." />
                <div className="flex-1 mt-[14px]" style={{ height: 2, background: '#e5eeff', borderRadius: 9999, margin: '14px 6px 0' }} />
                <PhaseStep n={3} label="Run Views"     status="pending" time="Pending" />
                <div className="flex-1 mt-[14px]" style={{ height: 2, background: '#e5eeff', borderRadius: 9999, margin: '14px 6px 0' }} />
                <PhaseStep n={4} label="Export DOCX"   status="pending" time="Pending" />
              </div>
            </div>

            {/* Activity row */}
            <div className="bg-white px-6 pb-5">
              <div className="bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <span className="material-symbols-outlined text-secondary" style={{ fontSize: 14 }} aria-hidden>psychology</span>
                    <p className="text-on-surface" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>Enriching function descriptions with LLM...</p>
                  </div>
                  <span className="text-secondary" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}>37%</span>
                </div>
                <div className="progress-track mb-2">
                  <div className="progress-fill" style={{ width: '37%', background: '#0058be' }} />
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>312 of 842 functions · LLM enrichment enabled</p>
                  <p style={{ color: '#74777d', fontFamily: "'JetBrains Mono'", fontSize: 11 }}>Est. ~4h 20m remaining</p>
                </div>
              </div>
              <div className="flex items-center gap-2 mt-2 px-1">
                <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 13 }} aria-hidden>info</span>
                <p className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>Job runs on the server — switch branches or close this tab safely. Return any time to check progress.</p>
              </div>
            </div>
          </div>
        )}

        {/* ══ STALE BANNER ══ */}
        {pageState === 'stale' && (
          <div className="mb-6 flex items-center gap-3 px-5 py-3.5 rounded-xl" style={{ background: '#fffbeb', border: '1px solid #f59e0b' }}>
            <span className="material-symbols-outlined sym-fill flex-shrink-0" style={{ fontSize: 20, color: '#d97706' }} aria-hidden>warning</span>
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-on-surface" style={{ fontSize: 13 }}>3 new commits since this analysis</p>
              <p style={{ fontSize: 11, color: '#74777d', fontFamily: "'JetBrains Mono'", marginTop: 2 }}>Results may be outdated — re-run to analyze the latest code.</p>
            </div>
            <button
              onClick={() => setPageState('running')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors flex-shrink-0"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 700, letterSpacing: '0.04em' }}
            >
              <span className="material-symbols-outlined sym-fill" style={{ fontSize: 14 }} aria-hidden>play_circle</span>
              Re-run
            </button>
          </div>
        )}

        {/* ══ KPI STRIP ══ */}
        {showContent && (
          <div className="mb-6" style={{ display: 'grid', gridTemplateColumns: '2fr 1fr 1fr', gap: '1rem' }}>
            <KpiCard label="Documents"  value={String(documents?.length ?? 45)} sub={`${reviewQueue.length} in review`} icon="description" color="#0058be" />
            <KpiCard label="Completion" value={`${project?.progress ?? 12}%`}    sub="across all processes" icon="fact_check" color="#00a572" />
            <KpiCard label="Version"    value={project?.latestVersion ?? 'v1.2.0'} sub="SWE.3 review draft" icon="sell" color="#f59e0b" />
          </div>
        )}

        {/* ══ CONTENT ROW ══ */}
        {showContent && (
          <div className="flex gap-6 items-stretch">

            {/* Left column */}
            <div className="flex-1 min-w-0 flex flex-col gap-4">

              {/* Documents table */}
              <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
                <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
                  <div>
                    <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Documents</h2>
                    <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                      {reviewQueue.length} in review · {project?.latestVersion ?? 'v1.2.0'}
                    </p>
                  </div>
                  <a
                    onClick={(e) => { e.preventDefault(); navigate(`/projects/${projectId}/documents`) }}
                    href="#"
                    className="text-secondary hover:underline"
                    style={{ fontSize: 12, fontWeight: 500, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                  >
                    View all
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>arrow_forward</span>
                  </a>
                </div>
                {docsLoading ? (
                  <TableSkeleton rows={5} cols={4} />
                ) : (
                  <table className="w-full">
                    <thead>
                      <tr className="bg-surface-container-low border-b border-outline-variant">
                        {['Process', 'Assignment', 'Team', ''].map((h, i) => (
                          <th
                            key={h + i}
                            className="text-left px-5 py-2.5 text-on-surface-variant uppercase"
                            style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.07em', width: i === 1 ? 210 : i === 2 ? 160 : i === 3 ? 44 : undefined }}
                          >
                            {h}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {previewDocs.map((doc) => (
                        <tr
                          key={doc.id}
                          className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors cursor-pointer"
                          onClick={() => navigate(`/projects/${projectId}/compare`)}
                        >
                          <td className="px-5 py-3">
                            <div className="flex flex-col gap-0.5">
                              <p className="text-on-surface font-medium" style={{ fontSize: 12 }}>{doc.name}</p>
                              <div><ProcessBadge process={doc.process} /></div>
                            </div>
                          </td>
                          <td className="px-4 py-3">
                            <Badge variant={STATUS_CONFIG[doc.status].variant}>{STATUS_CONFIG[doc.status].label}</Badge>
                          </td>
                          <td className="px-4 py-3 text-xs text-on-surface-variant">
                            {doc.assignee ?? <span className="text-outline">Unassigned</span>}
                          </td>
                          <td className="px-4 py-3 text-right">
                            <button
                              className="text-secondary hover:underline"
                              style={{ fontSize: 12 }}
                              onClick={(e) => { e.stopPropagation(); navigate(`/projects/${projectId}/compare`) }}
                            >
                              Review
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>

              {/* Unassigned pool — developer only */}
              {!isAdmin && unassigned.length > 0 && (
                <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
                  <div className="px-5 py-3.5 border-b border-outline-variant">
                    <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Available to Claim</h2>
                    <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                      {unassigned.length} unassigned document{unassigned.length !== 1 ? 's' : ''}
                    </p>
                  </div>
                  <div className="divide-y divide-outline-variant">
                    {unassigned.slice(0, 3).map((doc) => (
                      <div key={doc.id} className="flex items-center justify-between px-5 py-3">
                        <div>
                          <p className="text-on-surface font-medium" style={{ fontSize: 12 }}>{doc.name}</p>
                          <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{doc.process} · {doc.version}</p>
                        </div>
                        <Button size="sm" variant="secondary">
                          <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>add</span>
                          Claim
                        </Button>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Team card */}
              <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
                <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
                  <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Team</h2>
                  <button
                    onClick={() => navigate(`/projects/${projectId}/team`)}
                    className="flex items-center gap-1 px-2.5 py-1.5 border border-outline-variant hover:bg-surface-container text-on-surface-variant rounded-lg transition-colors"
                    style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500 }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>person_add</span>
                    Add
                  </button>
                </div>
                {teamLoading ? (
                  <div className="divide-y divide-outline-variant">
                    {Array.from({ length: 4 }).map((_, i) => (
                      <div key={i} className="flex items-center gap-3 px-4 py-2.5">
                        <div className="w-7 h-7 rounded-full bg-surface-container animate-pulse flex-shrink-0" />
                        <div className="flex-1 h-3 bg-surface-container animate-pulse rounded" />
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="divide-y divide-outline-variant">
                    {team?.map((m) => <TeamRow key={m.id} member={m} />)}
                  </div>
                )}
              </div>
            </div>

            {/* Right sidebar */}
            <div style={{ width: 300, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: '1rem' }}>

              {/* Review Queue — admin only */}
              {isAdmin && (
                <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
                  <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
                    <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Review Queue</h2>
                    <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700, background: '#e5eeff', color: '#0058be', padding: '2px 10px', borderRadius: 99 }}>
                      {reviewQueue.length} pending
                    </span>
                  </div>
                  <div className="divide-y divide-outline-variant">
                    {reviewQueue.length === 0 ? (
                      <p className="px-4 py-4 text-on-surface-variant" style={{ fontSize: 12 }}>Nothing in review.</p>
                    ) : reviewQueue.slice(0, 4).map((doc) => (
                      <div
                        key={doc.id}
                        className="px-4 py-3 flex items-center gap-3 hover:bg-surface-container-low transition-colors cursor-pointer"
                        onClick={() => navigate(`/projects/${projectId}/documents`)}
                      >
                        <div className="flex-1 min-w-0">
                          <p className="text-on-surface truncate" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}>{doc.name}</p>
                          <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{doc.assignee ?? 'Unassigned'}</p>
                        </div>
                        <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700, background: '#fff8e6', color: '#d97706', padding: '2px 7px', borderRadius: 99, flexShrink: 0 }}>
                          {doc.updatedAt}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Function Visibility — developer only */}
              {!isAdmin && (
                <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
                  <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
                    <div>
                      <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Function Visibility</h2>
                      <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>3 of 26 functions hidden from DOCX</p>
                    </div>
                  </div>
                  <div className="px-4 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <span className="material-symbols-outlined" style={{ fontSize: 14, color: '#ba1a1a' }} aria-hidden>visibility_off</span>
                      <span style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, color: '#ba1a1a' }}>3 hidden</span>
                    </div>
                    <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>Last: v1.1.0</span>
                  </div>
                </div>
              )}

              {/* Last Actions */}
              <div className="bg-white border border-outline-variant rounded-xl overflow-hidden flex-1">
                <div className="px-4 py-3.5 border-b border-outline-variant">
                  <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Last Actions</h2>
                </div>
                <div className="divide-y divide-outline-variant">
                  {[
                    { icon: 'check_circle', color: '#00a572', text: 'Sarah C. approved CAN-Matrix',      time: '1d ago' },
                    { icon: 'play_circle',  color: '#0058be', text: 'Manoj S. ran analysis — v1.2.0',   time: '3d ago' },
                    { icon: 'person_add',   color: '#7c3aed', text: 'Ana F. assigned to System Arch.',  time: '4d ago' },
                    { icon: 'sell',         color: '#00a572', text: 'v1.1.0 tagged — Engine complete',  time: '6d ago' },
                    { icon: 'rate_review',  color: '#f59e0b', text: 'Liam P. submitted Diagnostics',    time: '1w ago' },
                  ].map((item, i) => (
                    <div key={i} className="px-4 py-3 flex items-start gap-3 hover:bg-surface-container-low transition-colors">
                      <span className="material-symbols-outlined sym-fill flex-shrink-0 mt-0.5" style={{ fontSize: 16, color: item.color }} aria-hidden>{item.icon}</span>
                      <div className="flex-1 min-w-0">
                        <p className="text-on-surface" style={{ fontSize: 12 }}>{item.text}</p>
                        <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 10 }}>{item.time}</p>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

            </div>
          </div>
        )}

      </div>
    </div>
  )
}
