import { Fragment, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useDocuments, useTeam, useCommits, useVersions } from '../hooks/useProjects'
import { useSelfAssign } from '../hooks/useDocumentMutations'
import { useCurrentJob, useStartJob, useCancelJob, useJobEvents } from '../hooks/useJobs'
import { useProjectViewState } from '../hooks/useProjectViewState'
import { DashboardSkeleton, Icon, RoleBadge, Text } from '../components/ui'
import { cn } from '../lib/cn'
import { useAuthStore } from '../store/auth'
import type { StartJobInput } from '../services/api'
import type { DocStatus, TeamMember, JobPhase, JobPhaseStatus, Project, Commit, Version, Document } from '../types'

/* ── Job formatting helpers ── */
const PHASE_UI: Record<JobPhaseStatus, 'done' | 'active' | 'pending'> = {
  done: 'done', running: 'active', pending: 'pending', failed: 'pending',
}
function fmtClock(total: number): string {
  const s = Math.max(0, total)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${pad(h)}:${pad(m)}:${pad(sec)}`
}
function fmtEta(total: number): string {
  if (total >= 3600) return `${Math.floor(total / 3600)}h ${Math.round((total % 3600) / 60)}m`
  if (total >= 60) return `${Math.round(total / 60)}m`
  return `${total}s`
}
function phaseTime(p: JobPhase): string {
  if (p.status === 'done') return p.durationSeconds != null ? `Done · ${fmtEta(p.durationSeconds)}` : 'Done'
  if (p.status === 'running') return 'Running...'
  if (p.status === 'failed') return 'Failed'
  return 'Pending'
}
function fmtStart(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}


/* ─── Team member row ─── */
function TeamRow({ member }: { member: TeamMember }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 hover:bg-surface-container-low transition-colors">
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
        // eslint-disable-next-line no-restricted-syntax -- avatar colours are data-driven
        style={{ background: member.avatarColor, color: member.avatarTextColor }}
        aria-hidden
      >
        <span className="font-sans text-label font-bold">{member.initials}</span>
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-on-surface truncate font-mono text-xs font-medium">{member.name}</p>
      </div>
      <RoleBadge role={member.role} />
    </div>
  )
}

/* ─── Config info row ─── */
function InfoRow({ label, value, mono }: { label: string; value: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start gap-4 px-5 py-3">
      <span className="flex-shrink-0 text-on-surface-variant uppercase w-[116px] font-mono text-label font-medium tracking-[0.07em] pt-0.5">
        {label}
      </span>
      <span className={cn('flex-1 min-w-0 text-on-surface text-body break-words', mono && 'font-mono')}>
        {value}
      </span>
    </div>
  )
}

/* ─── Project configuration overview (shown before any analysis run) ─── */
function ConfigOverview({ project, team, teamLoading }: { project: Project; team?: TeamMember[]; teamLoading: boolean }) {
  const layers = project.architectureLayers
  const groupCount = layers.reduce((a, l) => a + l.groups.length, 0)
  const compCount = layers.reduce((a, l) => a + l.groups.reduce((b, g) => b + g.components.length, 0), 0)
  const defs = project.buildConfig.definitions
  const plural = (n: number, w: string) => `${n} ${w}${n !== 1 ? 's' : ''}`
  return (
    <div className="flex gap-6 items-stretch">
      {/* Left — configuration + architecture */}
      <div className="flex-1 min-w-0 flex flex-col gap-4">
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant">
            <Text as="h2" variant="heading" className="text-on-surface">Project Configuration</Text>
            <Text as="p" variant="caption" className="font-mono mt-0.5">Captured at setup · analysis not run yet</Text>
          </div>
          <div className="divide-y divide-outline-variant">
            <InfoRow label="Repository" mono value={project.repoPath || '—'} />
            <InfoRow label="Branch" mono value={project.defaultBranch || '—'} />
            <InfoRow label="Standard" value={project.standard || '—'} />
            {project.client && <InfoRow label="Client" value={project.client} />}
            {defs && (
              <InfoRow
                label="Defines"
                value={defs.mode === 'manual' ? `${plural(defs.count, 'definition')} (manual)` : `${defs.fileName ?? 'file'} (upload)`}
              />
            )}
            {project.buildConfig.dataDictionary && <InfoRow label="Data dictionary" mono value={project.buildConfig.dataDictionary} />}
          </div>
        </div>

        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
            <Text as="h2" variant="heading" className="text-on-surface">Architecture</Text>
            <Text variant="caption" className="font-mono">
              {plural(layers.length, 'layer')} · {plural(groupCount, 'group')} · {plural(compCount, 'component')}
            </Text>
          </div>
          {layers.length === 0 ? (
            <p className="px-5 py-5 text-on-surface-variant text-xs">No architecture mapped during setup.</p>
          ) : (
            <div className="divide-y divide-outline-variant">
              {layers.map((layer, li) => (
                <div key={li} className="px-5 py-3">
                  <div className="flex items-center gap-2">
                    <Icon name="layers" size={15} className="text-secondary" />
                    <span className="text-on-surface font-mono text-xs font-bold">{layer.name}</span>
                    {layer.path && <span className="text-on-surface-variant font-mono text-label">{layer.path}</span>}
                  </div>
                  {layer.groups.length === 0 ? (
                    <p className="text-on-surface-variant ml-[23px] mt-0.5 font-mono text-caption">No groups</p>
                  ) : layer.groups.map((g, gi) => (
                    <div key={gi} className="ml-[23px] mt-1">
                      <div className="flex items-center gap-1.5">
                        <Icon name="folder_open" size={13} className="text-secondary" />
                        <span className="text-on-surface font-mono text-caption font-semibold">{g.name}</span>
                        <span className="text-on-surface-variant font-mono text-label">{plural(g.components.length, 'comp')}</span>
                      </div>
                      {g.components.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 ml-5 mt-[3px]">
                          {g.components.map((c, ci) => (
                            <span key={ci} className="font-mono text-label bg-surface-container text-secondary px-[7px] py-0.5 rounded-lg">
                              {c.name}{c.files && c.files.length > 0 ? ` · ${c.files.length}` : ''}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right — team */}
      <div className="w-[300px] flex-shrink-0">
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-4 py-3.5 border-b border-outline-variant">
            <Text as="h2" variant="heading" className="text-on-surface">Team</Text>
            <Text as="p" variant="caption" className="font-mono mt-0.5">{plural(team?.length ?? 0, 'member')}</Text>
          </div>
          {teamLoading ? (
            <div className="divide-y divide-outline-variant">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-2.5">
                  <div className="w-7 h-7 rounded-full bg-surface-container animate-pulse flex-shrink-0" />
                  <div className="flex-1 h-3 bg-surface-container animate-pulse rounded" />
                </div>
              ))}
            </div>
          ) : team && team.length > 0 ? (
            <div className="divide-y divide-outline-variant">
              {team.map((m) => <TeamRow key={m.id} member={m} />)}
            </div>
          ) : (
            <p className="px-4 py-4 text-on-surface-variant text-xs">No members yet.</p>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─── Phase step (running panel) ─── */
type PhaseStatus = 'done' | 'active' | 'pending'
function PhaseStep({ n, label, status, time }: { n: number; label: string; status: PhaseStatus; time: string }) {
  const timeColor = status === 'done' ? 'text-[#00a572]' : status === 'active' ? 'text-secondary' : 'text-outline-variant'
  return (
    <div className="flex flex-col items-center text-center min-w-[105px]">
      <div
        className={cn(
          'w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0',
          status === 'done' ? 'bg-[#00a572]' : status === 'active' ? 'bg-secondary' : 'bg-surface-container',
        )}
      >
        {status === 'done' ? (
          <Icon name="check" size={14} fill className="text-white" />
        ) : status === 'active' ? (
          <div className="animate-spin w-3.5 h-3.5 rounded-full border-2 border-white/35 border-t-white" />
        ) : (
          <span className="text-body font-semibold text-outline">{n}</span>
        )}
      </div>
      <p className={cn('mt-1.5 font-semibold text-caption', status === 'pending' ? 'text-outline' : 'text-on-surface')}>Phase {n}</p>
      <p className="text-on-surface-variant text-label">{label}</p>
      <p className={cn('mt-0.5 text-label font-mono', timeColor)}>{time}</p>
    </div>
  )
}

/* ─── Run Analysis modal (matches project-detail.html) ─── */
function suggestNextVersion(versions?: Version[]): string {
  if (!versions || versions.length === 0) return 'v1.0.0'
  const m = versions[0].tag.match(/^v?(\d+)\.(\d+)\.(\d+)$/)
  return m ? `v${m[1]}.${parseInt(m[2], 10) + 1}.0` : ''
}

const SELECT_CLS = 'font-mono text-xs'
const FIELD_LABEL = 'text-caption font-mono'

function RunAnalysisModal({
  project, commits, versions, submitting, defaultSha, onClose, onStart,
}: {
  project: Project
  commits?: Commit[]
  versions?: Version[]
  submitting: boolean
  defaultSha?: string
  onClose: () => void
  onStart: (body: StartJobInput) => void
}) {
  const cs = commits ?? []
  const [commitSha, setCommitSha] = useState(defaultSha ?? cs[0]?.sha ?? '')
  const branch = cs.find((c) => c.sha === commitSha)?.branch || cs[0]?.branch || project.defaultBranch || 'main'
  const [referenceId, setReferenceId] = useState('')
  const [versionName, setVersionName] = useState(() => suggestNextVersion(versions))
  const [pause, setPause] = useState(false)
  const [advOpen, setAdvOpen] = useState(false)
  const [layerFilter, setLayerFilter] = useState('')

  const refVersions = (versions ?? []).filter((v): v is Version & { id: string } => !!v.id)
  const layerOptions = project.architectureLayers.flatMap((l) =>
    l.groups.map((g) => ({ value: g.name, label: `${l.name} — ${g.name}` })),
  )

  function submit() {
    if (!commitSha) return
    onStart({
      commit_sha: commitSha,
      version_tag: versionName.trim() || undefined,
      reference_version_id: referenceId || undefined,
      pause_after_phase1: pause,
      layer_filter: layerFilter || undefined,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(4,22,39,.55)]" onClick={onClose}>
      <div className="bg-white rounded-2xl w-full mx-4 max-w-[468px] shadow-[0_24px_64px_rgba(4,22,39,.28)]" onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="px-6 pt-6 pb-5 flex items-start justify-between">
          <div>
            <h3 className="text-on-surface font-semibold font-sans text-[17px] leading-[1.25]">Run Analysis</h3>
            <p className={cn('text-on-surface-variant mt-1', FIELD_LABEL)}>Analyze a commit and save it as a named version.</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-xl hover:bg-surface-container transition-colors text-on-surface-variant flex-shrink-0 -mt-1 -mr-2">
            <Icon name="close" size={19} />
          </button>
        </div>

        {/* Source card */}
        <div className="mx-6 mb-5 rounded-xl border border-outline-variant overflow-hidden">
          <div className="flex items-center gap-2.5 px-4 py-2.5 bg-surface-container-low border-b border-outline-variant">
            <Icon name="alt_route" size={14} className="text-on-surface-variant" />
            <span className={cn('text-on-surface-variant', FIELD_LABEL)}>Branch</span>
            <span className="font-mono text-xs font-bold text-on-surface">{branch}</span>
            <span className="ml-auto text-on-surface-variant text-label opacity-50 tracking-[.04em] font-mono">FIXED</span>
          </div>
          <div className="px-4 py-3">
            <label className={cn('text-on-surface-variant block mb-2', FIELD_LABEL)}>Commit</label>
            {cs.length === 0 ? (
              <p className="text-on-surface-variant text-xs font-mono">No commits available to analyze yet.</p>
            ) : (
              <select value={commitSha} onChange={(e) => setCommitSha(e.target.value)} className={cn('w-full rounded-lg px-3 py-2 text-on-surface bg-white cursor-pointer focus:outline-none border border-outline-variant', SELECT_CLS)}>
                {cs.map((c) => (
                  <option key={c.sha} value={c.sha}>
                    {c.shortSha}{c.versionTag ? ` [${c.versionTag}]` : ''} · {c.relativeTime} — {c.message}
                  </option>
                ))}
              </select>
            )}
          </div>
        </div>

        {/* Body */}
        <div className="px-6 space-y-4 pb-5">
          {/* Compare against */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label className={cn('text-on-surface-variant', FIELD_LABEL)}>Compare against</label>
              <span className="text-label text-outline-variant font-mono">OPTIONAL</span>
            </div>
            <select value={referenceId} onChange={(e) => setReferenceId(e.target.value)} className={cn('w-full border border-outline-variant rounded-lg px-3 py-2 text-on-surface bg-white cursor-pointer focus:outline-none', SELECT_CLS)}>
              <option value="">— None —</option>
              {refVersions.map((v) => (
                <option key={v.id} value={v.id}>{v.tag} · {v.shortSha} — {v.description}</option>
              ))}
            </select>
            <p className={cn('text-on-surface-variant mt-1.5', FIELD_LABEL)}>Enables diff view between this run and the selected version.</p>
          </div>

          {/* Version name */}
          <div>
            <label className={cn('text-on-surface-variant block mb-2', FIELD_LABEL)}>Version name</label>
            <div className="relative">
              <Icon name="sell" size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
              <input value={versionName} onChange={(e) => setVersionName(e.target.value)} type="text" placeholder="e.g. v1.3.0" autoComplete="off" spellCheck={false}
                className="w-full border border-outline-variant rounded-lg pl-9 pr-3 py-2.5 bg-white focus:outline-none font-mono text-body font-bold text-secondary tracking-[.03em] box-border" />
            </div>
          </div>

          {/* Pause after Phase 1 */}
          <label className="flex items-start gap-3 cursor-pointer group">
            <input type="checkbox" checked={pause} onChange={(e) => setPause(e.target.checked)} className="mt-0.5 rounded border-outline-variant text-secondary flex-shrink-0 w-[15px] h-[15px]" />
            <div>
              <span className="text-on-surface group-hover:text-secondary transition-colors text-xs">Pause after Phase 1 to review function visibility</span>
              <p className="text-on-surface-variant mt-0.5 text-caption">Lets you hide functions before diagrams and DOCX are generated.</p>
            </div>
          </label>

          {/* Advanced — Layer / Group filter */}
          {layerOptions.length > 0 && (
            <div>
              <button onClick={() => setAdvOpen((v) => !v)} className="flex items-center gap-2 w-full text-left py-0.5 group">
                <Icon name="chevron_right" size={14} className={cn('transition-transform text-on-surface-variant', advOpen && 'rotate-90')} />
                <span className="text-on-surface-variant group-hover:text-on-surface transition-colors text-caption tracking-[.05em] uppercase">Advanced</span>
                <div className="flex-1 h-px bg-outline-variant ml-1" />
              </button>
              {advOpen && (
                <div className="pt-3 pl-5">
                  <label className={cn('text-on-surface-variant block mb-2', FIELD_LABEL)}>Layer / Group</label>
                  <select value={layerFilter} onChange={(e) => setLayerFilter(e.target.value)} className={cn('w-full border border-outline-variant rounded-lg px-3 py-2 text-on-surface bg-white cursor-pointer focus:outline-none', SELECT_CLS)}>
                    <option value="">All layers (default)</option>
                    {layerOptions.map((o) => <option key={o.label} value={o.value}>{o.label}</option>)}
                  </select>
                </div>
              )}
            </div>
          )}

          {/* Warning */}
          <div className="flex items-center gap-2.5 rounded-xl px-4 py-3 bg-[#f0f4ff] border border-[#c7d8ff]">
            <Icon name="schedule" size={15} className="flex-shrink-0 text-secondary" />
            <p className="text-[#0b2e6b] text-caption">Analysis runs server-side and can take <strong>several hours</strong> — safe to navigate away.</p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-outline-variant flex items-center justify-between">
          <button onClick={onClose} className="px-4 py-2 text-on-surface-variant hover:bg-surface-container rounded-lg transition-colors text-sm">Cancel</button>
          <button onClick={submit} disabled={!commitSha || submitting} className="flex items-center gap-2 px-5 py-2.5 bg-secondary text-on-secondary rounded-xl transition-colors disabled:opacity-60 font-mono text-xs font-bold tracking-[.04em]">
            <Icon name="rocket_launch" size={16} fill />
            {submitting ? 'STARTING…' : 'START ANALYSIS'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* ════════════ Generated-state content (matches project-detail.html) ════════════ */

type Nav = (to: string) => void
type SelfAssign = { mutate: (id: string) => void; isPending: boolean }

const PROCESSES: { key: string; label: string }[] = [
  { key: 'SWE.3', label: 'Detailed Design' },
  { key: 'SYS.1', label: 'Req. Elicitation' },
  { key: 'SYS.2', label: 'System Architecture' },
  { key: 'SWE.1', label: 'SW Requirements' },
  { key: 'SWE.2', label: 'SW Architecture' },
]

const pct = (n: number, total: number) => (total ? Math.round((n / total) * 100) : 0)

/* Document status pill (design: approved / in_review / not-started) */
function DocStatusPill({ status }: { status: DocStatus }) {
  const cfg: Record<string, { cls: string; dot: string; label: string }> = {
    approved:  { cls: 'bg-[#f0fdf9] text-[#00a572] border-[#86efac]', dot: 'bg-[#00a572]', label: 'Approved' },
    in_review: { cls: 'bg-[#fff8e6] text-[#b45309] border-amber', dot: 'bg-amber', label: 'In Review' },
  }
  const c = cfg[status]
  if (!c) return (
    <span className="font-mono text-micro font-bold bg-[#f3f4f6] text-outline border border-[#e2e3e8] px-[9px] py-0.5 rounded-full uppercase tracking-[.04em]">Not Started</span>
  )
  return (
    <span className={cn('inline-flex items-center gap-1 font-mono text-micro font-bold border px-[9px] py-0.5 rounded-full uppercase tracking-[.04em]', c.cls)}>
      <span className={cn('w-[5px] h-[5px] rounded-full inline-block', c.dot)} />{c.label}
    </span>
  )
}

/* Small avatar from a document's (mapped) assignee colors */
function MiniAvatar({ doc, size = 24, ml = 0, z = 1 }: { doc: Document; size?: number; ml?: number; z?: number }) {
  const bg = doc.assigneeColor ?? '#e5eeff'
  const text = doc.assigneeTextColor ?? '#0058be'
  const initials = doc.assigneeInitials ?? (doc.assignee ?? '?').slice(0, 2).toUpperCase()
  return (
    <div
      title={doc.assignee}
      className="rounded-full border-2 border-white inline-flex items-center justify-center flex-shrink-0 relative"
      // eslint-disable-next-line no-restricted-syntax -- avatar size/colour/stacking are data-driven
      style={{ width: size, height: size, background: bg, marginLeft: ml, zIndex: z }}
    >
      {/* eslint-disable-next-line no-restricted-syntax -- avatar text size/colour are data-driven */}
      <span className="font-sans font-bold" style={{ fontSize: Math.round(size * 0.42), color: text }}>{initials}</span>
    </div>
  )
}

/* Document-status donut */
function Donut({ total, approved, inReview, notStarted }: { total: number; approved: number; inReview: number; notStarted: number }) {
  const C = 326.73
  const safe = total || 1
  const aArc = (approved / safe) * C
  const rArc = (inReview / safe) * C
  const nArc = (notStarted / safe) * C
  return (
    <svg width="136" height="136" viewBox="0 0 136 136">
      <g transform="rotate(-90 68 68)">
        <circle cx="68" cy="68" r="52" fill="none" stroke="#e8eaed" strokeWidth="14" />
        <circle cx="68" cy="68" r="52" fill="none" stroke="#00a572" strokeWidth="14" strokeDasharray={`${aArc.toFixed(2)} ${C.toFixed(2)}`} strokeDashoffset="0" />
        <circle cx="68" cy="68" r="52" fill="none" stroke="#f59e0b" strokeWidth="14" strokeDasharray={`${rArc.toFixed(2)} ${C.toFixed(2)}`} strokeDashoffset={(-aArc).toFixed(2)} />
        <circle cx="68" cy="68" r="52" fill="none" stroke="#c4c6cd" strokeWidth="14" strokeDasharray={`${nArc.toFixed(2)} ${C.toFixed(2)}`} strokeDashoffset={(-(aArc + rArc)).toFixed(2)} />
      </g>
      <text x="68" y="61" textAnchor="middle" fontSize="30" fontWeight="700" fill="#0b1c30" fontFamily="Inter,sans-serif">{total}</text>
      <text x="68" y="79" textAnchor="middle" fontSize="11" fill="#9aa0a6" fontFamily="Inter,sans-serif" letterSpacing="0.5">documents</text>
    </svg>
  )
}

const KPI_LABEL = 'font-mono text-caption font-medium tracking-[.07em]'

function KpiStrip({ documents, versions, team, isAdmin, meName }: {
  documents: Document[]; versions?: Version[]; team?: TeamMember[]; isAdmin: boolean; meName: string
}) {
  const total = documents.length
  const approved = documents.filter((d) => d.status === 'approved').length
  const inReview = documents.filter((d) => d.status === 'in_review').length
  const notStarted = Math.max(0, total - approved - inReview)
  const assigned = documents.filter((d) => !!d.assignee).length
  const unassigned = total - assigned
  const assignPct = pct(assigned, total)
  const latestTag = versions?.[0]?.tag ?? '—'
  const myDocs = documents.filter((d) => d.assignee && d.assignee === meName)
  const processCount = new Set(documents.map((d) => d.process)).size

  const statusRow = (dotCls: string, label: string, n: number) => (
    <div className="flex items-center justify-between">
      <div className="flex items-center gap-[9px]">
        <span className={cn('w-2.5 h-2.5 rounded-full flex-shrink-0', dotCls)} />
        <span className="text-body text-on-surface-variant">{label}</span>
      </div>
      <div className="flex items-center gap-2">
        <span className="font-mono text-title font-bold text-on-surface">{n}</span>
        <span className="text-caption text-[#9aa0a6] min-w-9 text-right">{pct(n, total)}%</span>
      </div>
    </div>
  )
  const infoRow = (label: string, value: ReactNode, pill?: boolean) => (
    <div className="flex items-center justify-between">
      <span className="text-xs text-outline">{label}</span>
      {pill
        ? <span className="font-mono text-caption font-bold text-secondary bg-surface-container px-[9px] py-0.5 rounded-[5px]">{value}</span>
        : <span className="font-mono text-body font-bold text-on-surface">{value}</span>}
    </div>
  )

  return (
    <div className="mb-6 grid grid-cols-[2fr_1fr_1fr] gap-4 items-stretch">
      <div className="bg-white border border-outline-variant rounded-xl p-6 flex items-center gap-8">
        <div className="flex-shrink-0"><Donut total={total} approved={approved} inReview={inReview} notStarted={notStarted} /></div>
        <div className="flex-1">
          <p className={cn('text-on-surface-variant uppercase mb-5', KPI_LABEL)}>Document Status</p>
          <div className="flex flex-col gap-[13px]">
            {statusRow('bg-[#00a572]', 'Approved', approved)}
            {statusRow('bg-amber', 'In Review', inReview)}
            {statusRow('bg-outline-variant', 'Not started', notStarted)}
          </div>
        </div>
      </div>

      {isAdmin ? (
        <div className="bg-white border border-outline-variant rounded-xl p-5">
          <p className={cn('text-on-surface-variant uppercase mb-3', KPI_LABEL)}>Assignment</p>
          <div className="flex items-baseline gap-1 mb-2.5">
            <span className="font-mono text-[32px] font-bold text-on-surface leading-none">{assigned}</span>
            <span className="text-body text-[#9aa0a6] leading-none">/ {total} assigned</span>
          </div>
          <div className="h-1.5 rounded-full bg-[#e8eaed] overflow-hidden mb-2.5">
            {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
            <div className={cn('h-full rounded-full', assignPct === 100 ? 'bg-[#00a572]' : 'bg-secondary')} style={{ width: `${assignPct}%` }} />
          </div>
          {unassigned > 0
            ? <p className="text-xs text-[#b45309]"><span className="font-semibold">{unassigned} docs</span> need an owner</p>
            : <p className="text-xs text-[#00a572] font-medium">All docs have owners</p>}
        </div>
      ) : (
        <div className="bg-white border border-outline-variant rounded-xl p-5">
          <p className={cn('text-on-surface-variant uppercase mb-3', KPI_LABEL)}>My Assignments</p>
          <div className="flex items-baseline gap-1 mb-2.5">
            <span className="font-mono text-[32px] font-bold text-on-surface leading-none">{myDocs.length}</span>
            <span className="text-body text-[#9aa0a6] leading-none">/ {total} docs</span>
          </div>
          <div className="h-1.5 rounded-full bg-[#e8eaed] overflow-hidden mb-2.5">
            {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
            <div className="h-full bg-secondary rounded-full" style={{ width: `${pct(myDocs.length, total)}%` }} />
          </div>
          <div className="flex gap-3 flex-wrap">
            <span className="flex items-center gap-[5px]"><span className="w-[7px] h-[7px] rounded-full bg-amber" /><span className="text-caption text-outline">{myDocs.filter((d) => d.status === 'in_review').length} in review</span></span>
            <span className="flex items-center gap-[5px]"><span className="w-[7px] h-[7px] rounded-full bg-[#00a572]" /><span className="text-caption text-outline">{myDocs.filter((d) => d.status === 'approved').length} approved</span></span>
          </div>
        </div>
      )}

      <div className="bg-white border border-outline-variant rounded-xl p-5">
        <p className={cn('text-on-surface-variant uppercase mb-3', KPI_LABEL)}>Project Info</p>
        <div className="flex flex-col gap-2.5">
          {infoRow('Latest version', latestTag, true)}
          {infoRow('Team members', team?.length ?? 0)}
          {infoRow('Processes', processCount)}
          {infoRow('Versions', versions?.length ?? 0)}
        </div>
      </div>
    </div>
  )
}

const DOC_TH = 'text-left px-4 py-2.5 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[.07em]'

function AdminDocsCard({ documents, go, projectId }: { documents: Document[]; go: Nav; projectId: string }) {
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <Text as="h2" variant="heading" className="text-on-surface">Documents</Text>
        <a onClick={(e) => { e.preventDefault(); go(`/projects/${projectId}/documents`) }} href="#" className="hover:underline inline-flex items-center gap-1 text-xs text-secondary font-medium">
          View all<Icon name="arrow_forward" size={14} />
        </a>
      </div>
      <table className="w-full">
        <thead>
          <tr className="bg-surface-container-low border-b border-outline-variant">
            <th className="text-left px-5 py-2.5 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[.07em]">Process</th>
            <th className={cn(DOC_TH, 'w-[210px]')}>Assignment</th>
            <th className={cn(DOC_TH, 'w-40')}>Team</th>
            <th className="w-11" />
          </tr>
        </thead>
        <tbody>
          {PROCESSES.map((p) => {
            const docs = documents.filter((d) => d.process === p.key)
            if (!docs.length) return null
            const total = docs.length
            const assigned = docs.filter((d) => !!d.assignee).length
            const unassigned = total - assigned
            const apct = pct(assigned, total)
            const barColor = apct === 100 ? 'bg-[#00a572]' : apct === 0 ? 'bg-[#e2e3e8]' : 'bg-amber'
            const textColor = apct === 100 ? 'text-[#00a572]' : apct === 0 ? 'text-[#9aa0a6]' : 'text-[#b45309]'
            const seen = new Set<string>()
            const reps: Document[] = []
            docs.forEach((d) => { const k = d.assigneeInitials ?? d.assignee; if (d.assignee && k && !seen.has(k)) { seen.add(k); reps.push(d) } })
            const shown = reps.slice(0, 4)
            const extra = reps.length - shown.length
            return (
              <tr key={p.key} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors cursor-pointer" onClick={() => go(`/projects/${projectId}/documents`)}>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-2.5">
                    <span className="font-mono text-caption font-bold text-secondary bg-surface-container px-2 py-0.5 rounded-[5px] flex-shrink-0">{p.key}</span>
                    <div>
                      <div className="text-body font-medium text-on-surface leading-[1.3]">{p.label}</div>
                      <div className="text-caption text-outline">{total} doc{total !== 1 ? 's' : ''}</div>
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 h-1 rounded-full bg-[#e8eaed] overflow-hidden min-w-[72px]">
                      {/* eslint-disable-next-line no-restricted-syntax -- assignment bar width is data-driven */}
                      <div className={cn('h-full rounded-full', barColor)} style={{ width: `${apct}%` }} />
                    </div>
                    <span className={cn('text-caption font-semibold whitespace-nowrap', textColor)}>{assigned} / {total}</span>
                    {unassigned > 0 && <span className="text-label text-[#b45309] bg-[#fff8e6] border border-amber px-1.5 rounded-full font-semibold whitespace-nowrap">{unassigned} left</span>}
                  </div>
                </td>
                <td className="px-4 py-3">
                  {shown.length === 0
                    ? <span className="text-caption text-outline-variant italic">Unassigned</span>
                    : <div className="flex items-center">{shown.map((d, i) => <MiniAvatar key={d.id} doc={d} size={24} ml={i > 0 ? -6 : 0} z={10 - i} />)}{extra > 0 && <div className="-ml-1.5 w-6 h-6 rounded-full bg-[#f3f4f6] border-2 border-white flex items-center justify-center text-micro font-bold text-on-surface-variant">+{extra}</div>}</div>}
                </td>
                <td className="px-3 py-2 text-right"><Icon name="arrow_forward" size={14} className="text-on-surface-variant" /></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function DevDocsCard({ documents, meName, go, projectId }: { documents: Document[]; meName: string; go: Nav; projectId: string }) {
  const myDocs = documents.filter((d) => d.assignee && d.assignee === meName)
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-5 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <div>
          <Text as="h2" variant="heading" className="text-on-surface">My Documents</Text>
          <Text as="p" variant="caption" className="font-mono mt-0.5">{myDocs.length} document{myDocs.length !== 1 ? 's' : ''} assigned to you</Text>
        </div>
        <a onClick={(e) => { e.preventDefault(); go(`/projects/${projectId}/documents`) }} href="#" className="hover:underline inline-flex items-center gap-1 text-xs text-secondary font-medium">
          All Documents<Icon name="arrow_forward" size={14} />
        </a>
      </div>
      {myDocs.length === 0 ? (
        <p className="px-5 py-6 text-on-surface-variant text-xs">Nothing assigned to you yet.</p>
      ) : (
        <table className="w-full">
          <thead>
            <tr className="bg-surface-container-low border-b border-outline-variant">
              <th className="text-left px-5 py-2.5 text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[.07em]">Document</th>
              <th className={cn(DOC_TH, 'w-[100px]')}>Process</th>
              <th className={cn(DOC_TH, 'w-[120px]')}>Status</th>
              <th className={cn(DOC_TH, 'w-[90px]')}>Due</th>
              <th className="w-[72px]" />
            </tr>
          </thead>
          <tbody>
            {myDocs.map((doc) => (
              <tr key={doc.id} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors cursor-pointer" onClick={() => go(`/projects/${projectId}/documents`)}>
                <td className="px-5 py-[13px]">
                  <div className="text-body font-medium text-on-surface leading-[1.3]">{doc.name}</div>
                  <div className="text-caption text-outline mt-0.5">{doc.subtitle ?? doc.process}</div>
                </td>
                <td className="px-4 py-[13px]"><span className="font-mono text-caption font-bold text-secondary bg-surface-container px-2 py-0.5 rounded-[5px]">{doc.process}</span></td>
                <td className="px-4 py-[13px]"><DocStatusPill status={doc.status} /></td>
                <td className="px-4 py-[13px] font-mono text-caption text-on-surface-variant">{doc.due ?? '—'}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    <button onClick={(e) => e.stopPropagation()} title="Open" className="flex items-center justify-center w-7 h-7 border border-[#e2e3e8] rounded-md bg-white text-outline cursor-pointer"><Icon name="open_in_new" size={14} /></button>
                    <button onClick={(e) => e.stopPropagation()} title="Download" className="flex items-center justify-center w-7 h-7 border border-[#e2e3e8] rounded-md bg-white text-outline cursor-pointer"><Icon name="download" size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function ClaimPoolCard({ documents, selfAssign }: { documents: Document[]; selfAssign: SelfAssign }) {
  const pool = documents.filter((d) => !d.assignee)
  if (!pool.length) return null
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-5 py-3.5 border-b border-outline-variant">
        <Text as="h2" variant="heading" className="text-on-surface">Available to Claim</Text>
        <Text as="p" variant="caption" className="font-mono mt-0.5">{pool.length} document{pool.length !== 1 ? 's' : ''} without an owner</Text>
      </div>
      <div>
        {pool.map((doc) => (
          <div key={doc.id} className="flex items-center gap-3 px-5 py-3 border-b border-[#e2e3e8]">
            <Icon name="description" size={18} className="text-outline-variant flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="text-body font-medium text-on-surface truncate">{doc.name}</div>
              <div className="flex items-center gap-1.5 mt-[3px]">
                <span className="font-mono text-label font-bold text-secondary bg-surface-container px-[7px] py-px rounded-lg">{doc.process}</span>
                <span className="text-caption text-outline">{doc.subtitle ?? ''}</span>
              </div>
            </div>
            <button onClick={() => selfAssign.mutate(doc.id)} disabled={selfAssign.isPending} className="inline-flex items-center gap-[5px] px-3 py-[5px] rounded-lg border border-secondary bg-white text-secondary text-xs font-semibold cursor-pointer whitespace-nowrap flex-shrink-0">
              <Icon name="add" size={14} />Claim
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

function TeamCard({ team, teamLoading, go, projectId }: { team?: TeamMember[]; teamLoading: boolean; go: Nav; projectId: string }) {
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <Text as="h2" variant="heading" className="text-on-surface">Team</Text>
        <button onClick={() => go(`/projects/${projectId}/team`)} className="flex items-center gap-1 px-2.5 py-1.5 border border-outline-variant hover:bg-surface-container text-on-surface-variant rounded-lg transition-colors font-mono text-caption font-medium">
          <Icon name="person_add" size={14} />Add
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
        <div className="divide-y divide-outline-variant">{team?.map((m) => <TeamRow key={m.id} member={m} />)}</div>
      )}
    </div>
  )
}

function ReviewQueueCard({ documents, go, projectId }: { documents: Document[]; go: Nav; projectId: string }) {
  const queue = documents.filter((d) => d.status === 'in_review')
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <Text as="h2" variant="heading" className="text-on-surface">Review Queue</Text>
        <span className="font-mono text-label font-bold bg-surface-container text-secondary px-2.5 py-0.5 rounded-full">{queue.length} pending</span>
      </div>
      <div className="divide-y divide-outline-variant">
        {queue.length === 0
          ? <p className="px-4 py-4 text-on-surface-variant text-xs">Nothing in review.</p>
          : queue.slice(0, 4).map((doc) => (
            <div key={doc.id} className="px-4 py-3 flex items-center gap-3 hover:bg-surface-container-low transition-colors cursor-pointer" onClick={() => go(`/projects/${projectId}/documents`)}>
              <div className="flex-1 min-w-0">
                <p className="text-on-surface truncate font-mono text-xs font-medium">{doc.name}</p>
                <p className="text-on-surface-variant mt-0.5 font-mono text-caption">{doc.assignee ?? 'Unassigned'}</p>
              </div>
              <span className="font-mono text-label font-bold bg-[#fff8e6] text-[#d97706] px-[7px] py-0.5 rounded-full flex-shrink-0">{doc.due ?? doc.updatedAt}</span>
            </div>
          ))}
      </div>
    </div>
  )
}

function FunctionVisibilityCard({ latestVersion }: { latestVersion: string }) {
  // Placeholder — no function-visibility endpoint yet (see INTEGRATION_NOTES).
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <div>
          <Text as="h2" variant="heading" className="text-on-surface">Function Visibility</Text>
          <Text as="p" variant="caption" className="font-mono mt-0.5">3 of 26 functions hidden from DOCX</Text>
        </div>
        <button className="flex items-center gap-1 px-3 py-1.5 border border-outline-variant rounded-lg hover:bg-surface-container transition-colors text-secondary font-mono text-caption">
          Manage<Icon name="arrow_forward" size={14} />
        </button>
      </div>
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon name="visibility_off" size={14} className="text-error" />
          <span className="font-mono text-xs text-error">3 hidden</span>
        </div>
        <span className="text-on-surface-variant font-mono text-caption">Last: {latestVersion}</span>
      </div>
    </div>
  )
}

// Placeholder activity feeds (no activity/audit endpoint yet — see INTEGRATION_NOTES).
const LAST_ACTIONS_ADMIN = [
  { icon: 'check_circle', color: 'text-[#00a572]', text: 'Sarah C. approved CAN-Matrix', time: '1d ago' },
  { icon: 'play_circle', color: 'text-secondary', text: 'Manoj S. ran analysis — v1.2.0', time: '3d ago' },
  { icon: 'person_add', color: 'text-[#7c3aed]', text: 'Ana F. assigned to System Architecture', time: '4d ago' },
  { icon: 'sell', color: 'text-[#00a572]', text: 'v1.1.0 tagged — Engine + Brake complete', time: '6d ago' },
  { icon: 'rate_review', color: 'text-amber', text: 'Liam P. submitted Diagnostics for review', time: '1w ago' },
]
const LAST_ACTIONS_DEV = [
  { icon: 'check_circle', color: 'text-[#00a572]', text: 'Sarah C. approved your Brake-FMEA', time: '1d ago' },
  { icon: 'play_circle', color: 'text-secondary', text: 'Analysis ran — v1.2.0 ready', time: '3d ago' },
  { icon: 'person_add', color: 'text-[#7c3aed]', text: 'Zara P. assigned you to Detailed SW Design', time: '5d ago' },
  { icon: 'rate_review', color: 'text-amber', text: 'Ana F. submitted System Arch for review', time: '1w ago' },
]

function LastActionsCard({ isAdmin }: { isAdmin: boolean }) {
  const actions = isAdmin ? LAST_ACTIONS_ADMIN : LAST_ACTIONS_DEV
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden flex-1 flex flex-col">
      <div className="px-4 py-3.5 border-b border-outline-variant">
        <Text as="h2" variant="heading" className="text-on-surface">Last Actions</Text>
      </div>
      <div className="flex-1 overflow-y-auto">
        {actions.map((a, i) => (
          <div key={i} className="flex items-start gap-2.5 px-4 py-3 border-b border-[#f0f1f3]">
            <Icon name={a.icon} size={15} fill className={cn('flex-shrink-0 mt-px', a.color)} />
            <div className="flex-1 min-w-0">
              <p className="text-xs text-on-surface leading-[1.4]">{a.text}</p>
              <p className="text-label text-[#9aa0a6] mt-0.5 font-mono">{a.time}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

function GeneratedContent({ project, documents, team, versions, isAdmin, projectId, go, selfAssign, meName, teamLoading }: {
  project: Project; documents?: Document[]; team?: TeamMember[]; versions?: Version[]
  isAdmin: boolean; projectId: string; go: Nav; selfAssign: SelfAssign; meName: string; teamLoading: boolean
}) {
  const docs = documents ?? []
  const latestVersion = project.latestVersion ?? versions?.[0]?.tag ?? 'v1.0.0'
  return (
    <>
      <KpiStrip documents={docs} versions={versions} team={team} isAdmin={isAdmin} meName={meName} />
      <div className="flex gap-6 mb-8 items-stretch">
        <div className="flex-1 min-w-0 flex flex-col gap-4">
          {isAdmin
            ? <AdminDocsCard documents={docs} go={go} projectId={projectId} />
            : <DevDocsCard documents={docs} meName={meName} go={go} projectId={projectId} />}
          {!isAdmin && <ClaimPoolCard documents={docs} selfAssign={selfAssign} />}
          {isAdmin && <TeamCard team={team} teamLoading={teamLoading} go={go} projectId={projectId} />}
        </div>
        <div className="w-[300px] flex-shrink-0 flex flex-col gap-4">
          {isAdmin && <ReviewQueueCard documents={docs} go={go} projectId={projectId} />}
          <FunctionVisibilityCard latestVersion={latestVersion} />
          <LastActionsCard isAdmin={isAdmin} />
        </div>
      </div>
    </>
  )
}

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const meName = useAuthStore((s) => s.user?.name ?? '')

  const { data: project } = useProject(projectId ?? '')
  // pageState + the version to view come from the Subbar selection (shared store).
  const { pageState, isLoading, viewVersionId, selectedCommit } = useProjectViewState(projectId ?? '')
  const { data: documents, isLoading: documentsLoading } = useDocuments(projectId ?? '', viewVersionId ? { versionId: viewVersionId } : undefined)
  const { data: team, isLoading: teamLoading } = useTeam(projectId ?? '')
  const { data: commits } = useCommits(projectId ?? '')
  const { data: job } = useCurrentJob(projectId ?? '')
  const selfAssign = useSelfAssign(projectId ?? '')
  const startJob = useStartJob(projectId ?? '')
  const cancelJob = useCancelJob(projectId ?? '')
  const { data: versions } = useVersions(projectId ?? '')
  const [runOpen, setRunOpen] = useState(false)
  useJobEvents(projectId ?? '', job?.id, job?.status)

  // Role is per-project (API's my_role → project.userRole).
  const isAdmin = project?.userRole === 'admin'

  // The commit shown in the empty/run states: the picker selection, else latest.
  const shownCommit = selectedCommit ?? commits?.[0]
  const startAnalysis = (body: StartJobInput) =>
    startJob.mutate(body, { onSuccess: () => setRunOpen(false) })

  const showContent = ['in_review', 'complete', 'stale'].includes(pageState)

  return (
    <div className="flex-1 overflow-y-auto bg-background">
      <div className="px-6 py-6 max-w-[1280px] mx-auto">

        {/* ══ LOADING — gate the empty-state flash until the view state resolves ══ */}
        {isLoading && !project ? (
          <DashboardSkeleton />
        ) : (
          <>

        {/* ══ EMPTY STATE (not yet analysed) ══ */}
        {pageState === 'never' && (
          <>
            <div className="mb-6 rounded-xl border border-outline-variant bg-white px-8 py-10 flex flex-col items-center text-center gap-5">
              <div className="w-14 h-14 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
                <Icon name="auto_awesome" size={28} className="text-on-surface-variant" />
              </div>
              <div>
                <Text as="h3" variant="heading" className="text-on-surface">No documents generated yet</Text>
                <p className="text-on-surface-variant mt-2 font-mono text-caption max-w-[340px]">
                  Run analysis on <strong>{shownCommit ? `${shownCommit.branch} @ ${shownCommit.shortSha}` : 'the latest commit'}</strong> to generate ASPICE-compliant documents for all 5 processes.
                </p>
              </div>
              <button
                onClick={() => setRunOpen(true)}
                disabled={!isAdmin}
                className="flex items-center gap-2 px-5 py-2.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-xl transition-colors disabled:opacity-60 font-mono text-xs font-bold tracking-[0.04em]"
              >
                <Icon name="play_circle" size={16} fill />
                RUN ANALYSIS
              </button>
            </div>

            {/* Show the captured project configuration even before analysis runs. */}
            {project && <ConfigOverview project={project} team={team} teamLoading={teamLoading} />}
          </>
        )}

        {/* ══ RUNNING STATE ══ */}
        {pageState === 'running' && job && (
          <div className="mb-7 rounded-xl overflow-hidden border border-outline-variant">
            {/* Dark header */}
            <div className="px-5 py-4 flex items-center justify-between bg-primary">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 border-2 border-secondary border-t-transparent">
                  <div className="animate-spin w-full h-full rounded-full border-2 border-secondary border-t-transparent" />
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <p className="text-white font-semibold font-sans text-sm">
                      Analysis {job.status === 'paused' ? 'Paused' : 'Running'}
                    </p>
                    <span className="font-mono text-micro font-bold bg-secondary text-white px-[7px] py-px rounded-[3px] uppercase tracking-[0.05em]">Live</span>
                  </div>
                  {(() => {
                    // Show the version being generated by default; fall back to
                    // branch @ commit only when a specific (non-latest) commit was chosen.
                    const onLatest = !commits?.[0] || job.commitSha === commits[0].sha
                    const showVersion = onLatest && !!job.versionTag
                    return (
                      <div className="flex items-center gap-2 mt-0.5 text-on-primary-container">
                        {showVersion ? (
                          <>
                            <Icon name="sell" size={12} />
                            <p className="text-caption font-mono">Version <span className="text-[#4d9fff]">{job.versionTag}</span></p>
                          </>
                        ) : (
                          <>
                            <Icon name="source" size={12} />
                            <p className="text-caption font-mono">Branch <span className="text-[#4d9fff]">{job.branch}</span></p>
                            <span className="text-[#1e3045]">·</span>
                            <p className="text-caption font-mono">Commit <span className="text-[#4d9fff]">{job.shortSha}</span></p>
                          </>
                        )}
                      </div>
                    )
                  })()}
                </div>
              </div>
              <div className="flex items-center gap-5">
                <div className="text-right">
                  <p className="text-label font-mono text-on-surface-variant uppercase tracking-[0.08em]">Started</p>
                  <p className="font-mono text-xs text-on-primary-container">{fmtStart(job.startedAt)}</p>
                </div>
                <div className="text-right">
                  <p className="text-label font-mono text-on-surface-variant uppercase tracking-[0.08em]">Elapsed</p>
                  <p className="font-mono text-xs text-white">{fmtClock(job.elapsedSeconds)}</p>
                </div>
                {isAdmin && (
                  <button
                    onClick={() => cancelJob.mutate(job.id)}
                    disabled={cancelJob.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-60 border border-[#4d2020] text-[#ff7070] font-mono text-caption font-medium"
                  >
                    <Icon name="stop_circle" size={14} />
                    Cancel Job
                  </button>
                )}
              </div>
            </div>

            {/* Phase steps (driven by the live job) */}
            <div className="bg-white px-6 pt-5 pb-3">
              <div className="flex items-start">
                {job.phases.map((p, i) => (
                  <Fragment key={p.number}>
                    {i > 0 && (
                      <div className={cn('flex-1 h-0.5 rounded-full mt-3.5 mx-1.5', p.status !== 'pending' ? 'bg-[#00a572]' : 'bg-surface-container')} />
                    )}
                    <PhaseStep n={p.number} label={p.name} status={PHASE_UI[p.status]} time={phaseTime(p)} />
                  </Fragment>
                ))}
              </div>
            </div>

            {/* Activity row */}
            <div className="bg-white px-6 pb-5">
              <div className="bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Icon name="psychology" size={14} className="text-secondary" />
                    <p className="text-on-surface font-mono text-caption">{job.currentActivity}</p>
                  </div>
                  <span className="text-secondary font-mono text-xs font-medium">{job.phasePct}%</span>
                </div>
                <div className="progress-track mb-2">
                  {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
                  <div className="progress-fill bg-secondary" style={{ width: `${job.phasePct}%` }} />
                </div>
                <div className="flex items-center justify-between">
                  <p className="text-on-surface-variant font-mono text-caption">{job.activityDetail || '—'}</p>
                  {job.etaSeconds != null && (
                    <p className="text-outline font-mono text-caption">Est. ~{fmtEta(job.etaSeconds)} remaining</p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-2 mt-2 px-1">
                <Icon name="info" size={13} className="text-on-surface-variant" />
                <p className="text-on-surface-variant font-mono text-caption">Job runs on the server — switch branches or close this tab safely. Return any time to check progress.</p>
              </div>
            </div>
          </div>
        )}

        {/* ══ STALE BANNER ══ */}
        {pageState === 'stale' && (
          <div className="mb-6 flex items-center gap-3 px-5 py-3.5 rounded-xl bg-[#fffbeb] border border-amber">
            <Icon name="warning" size={20} fill className="flex-shrink-0 text-[#d97706]" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-on-surface text-body">3 new commits since this analysis</p>
              <p className="text-caption text-outline font-mono mt-0.5">Results may be outdated — re-run to analyze the latest code.</p>
            </div>
            <button
              onClick={() => setRunOpen(true)}
              disabled={!isAdmin}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors flex-shrink-0 disabled:opacity-60 font-mono text-caption font-bold tracking-[0.04em]"
            >
              <Icon name="play_circle" size={14} fill />
              Re-run
            </button>
          </div>
        )}

        {/* ══ GENERATED CONTENT — KPI strip + docs + sidebar (matches project-detail.html) ══ */}
        {showContent && project && (
          documentsLoading && !documents ? (
            <DashboardSkeleton />
          ) : (
            <GeneratedContent
              project={project}
              documents={documents}
              team={team}
              versions={versions}
              isAdmin={isAdmin}
              projectId={projectId ?? ''}
              go={(to) => navigate(to)}
              selfAssign={selfAssign}
              meName={meName}
              teamLoading={teamLoading}
            />
          )
        )}

          </>
        )}

      </div>

      {runOpen && project && (
        <RunAnalysisModal
          project={project}
          commits={commits}
          versions={versions}
          submitting={startJob.isPending}
          defaultSha={shownCommit?.sha}
          onClose={() => setRunOpen(false)}
          onStart={startAnalysis}
        />
      )}
    </div>
  )
}
