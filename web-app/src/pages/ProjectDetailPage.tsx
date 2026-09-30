import { Fragment, useEffect, useState, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useDocuments, useTeam, useCommits, useVersions, useDownloadProjectConfig } from '../hooks/useProjects'
import { useDownloadDoc, useSelfAssign } from '../hooks/useDocumentMutations'
import { docxFileName } from '../lib/docTree'
import { useCurrentJob, useStartJob, useCancelJob, useJobEvents, useJobFunctions } from '../hooks/useJobs'
import { useProjectViewState } from '../hooks/useProjectViewState'
import { CodeText, DashboardSkeleton, Icon, RoleBadge, Text } from '../components/ui'
import { SubbarCta } from '../components/shell/SubbarCta'
import { cn } from '../lib/cn'
import { useAuthStore } from '../store/auth'
import type { StartJobInput } from '../services/api'
import { ScopeTree } from '../components/run/ScopeTree'
import { allKeys, scopeOf } from '../lib/runScope'
import type { AnalysisJob, DocStatus, TeamMember, JobPhase, JobPhaseStatus, Project, Commit, Version, Document } from '../types'
import { relativeTime } from '../lib/format'

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
  const cores = project.buildConfig.cores
  const plural = (n: number, w: string) => `${n} ${w}${n !== 1 ? 's' : ''}`
  const downloadConfig = useDownloadProjectConfig(project.id)
  return (
    <div className="flex gap-6 items-stretch">
      {/* Left — configuration + architecture */}
      <div className="flex-1 min-w-0 flex flex-col gap-4">
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
          <div className="px-5 py-3.5 border-b border-outline-variant flex items-start justify-between gap-3">
            <div>
              <Text as="h2" variant="heading" className="text-on-surface">Project Configuration</Text>
              <Text as="p" variant="caption" className="font-mono mt-0.5">Captured at setup · analysis not run yet</Text>
            </div>
            <button
              onClick={() => { void downloadConfig(project.name) }}
              title="The project as a config file — the command line and the New Project wizard read it"
              className="flex items-center gap-1 px-3 py-1.5 border border-outline-variant rounded-lg hover:bg-surface-container transition-colors text-secondary font-mono text-caption flex-shrink-0"
            >
              <Icon name="download" size={14} />Download config
            </button>
          </div>
          <div className="divide-y divide-outline-variant">
            <InfoRow label="Repository" mono value={project.repoPath || '—'} />
            <InfoRow label="Branch" mono value={project.defaultBranch || '—'} />
            <InfoRow label="Standard" value={project.standard || '—'} />
            {project.client && <InfoRow label="Client" value={project.client} />}
            <InfoRow
              label="Cores"
              value={cores.length ? (
                <div className="space-y-1.5">
                  {cores.map((c) => (
                    <div key={c.name}>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <Icon name="memory" size={14} className="text-secondary" />
                        <span className="font-mono text-xs font-semibold">{c.name}</span>
                        <span className={cn('font-mono text-label', c.layers.length ? 'text-on-surface-variant' : 'text-[#b45309]')}>
                          {c.layers.length ? `used by ${c.layers.join(', ')}` : 'no layer uses it'}
                        </span>
                      </div>
                      <div className="ml-5 text-on-surface-variant font-mono text-label">
                        {[c.macros ?? 'no macros', c.dataDictionary ?? 'no dictionary', c.compileCommands ?? 'no compile commands'].join(' · ')}
                      </div>
                    </div>
                  ))}
                </div>
              ) : 'None: every layer is parsed without macros or a data dictionary'}
            />
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
                    {layer.core && (
                      <span className="ml-auto flex items-center gap-1 text-secondary font-mono text-label" title="The core this layer is built for">
                        <Icon name="memory" size={12} />{layer.core}
                      </span>
                    )}
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
      <p className={cn('mt-1.5 font-semibold text-body', status === 'pending' ? 'text-outline' : 'text-on-surface')}>{label}</p>
      <p className={cn('mt-0.5 text-label font-mono', timeColor)}>{time}</p>
    </div>
  )
}

/* ─── The run that made the version on screen warned about something ─── */
// A path the checkout did not have (of a component with other files), a dictionary the run went
// without: the run still finished, so nothing else says so - and its documents lack those.
function RunWarningsBanner({ version }: { version: Version }) {
  const [open, setOpen] = useState(false)
  const n = version.warnings.length
  const shown = open ? version.warnings : version.warnings.slice(0, 3)
  return (
    <div role="status" className="mb-6 rounded-xl border border-amber bg-[#fff8e6] px-5 py-4">
      <div className="flex items-start gap-3">
        <Icon name="warning" size={20} fill className="flex-shrink-0 text-[#d97706] mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-on-surface text-body">
            The run that made {version.tag} reported {n} warning{n === 1 ? '' : 's'}
          </p>
          <p className="text-caption text-on-surface-variant mt-0.5">
            Its documents were generated, but without what these name.
          </p>
          <ul className="mt-2 ml-5 list-disc space-y-1">
            {shown.map((w, i) => (
              <li key={i} className="text-xs text-on-surface leading-[1.45] break-words"><CodeText text={w} /></li>
            ))}
          </ul>
          {n > 3 && (
            <button onClick={() => setOpen((v) => !v)} className="mt-2 flex items-center gap-1 text-caption font-mono text-secondary hover:underline">
              <Icon name={open ? 'expand_less' : 'expand_more'} size={14} />
              {open ? 'Show fewer' : `Show all ${n}`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─── The project's latest run ended in an error ─── */
function FailedRunBanner({ job, isAdmin, onRerun }: { job: AnalysisJob; isAdmin: boolean; onRerun: () => void }) {
  const [open, setOpen] = useState(false)
  const lines = (job.errorMessage ?? '').trim().split('\n')
  const headline = lines[0] || 'The analysis stopped with an error.'
  const details = lines.slice(1).join('\n').trim()
  return (
    <div role="alert" className="mb-6 rounded-xl border border-error/40 bg-error-container/40 px-5 py-4">
      <div className="flex items-start gap-3">
        <Icon name="error" size={20} fill className="flex-shrink-0 text-error mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="font-semibold text-on-surface text-body">
            Last analysis failed{job.versionTag ? ` — ${job.versionTag}` : ''}
          </p>
          <p className="text-caption text-outline font-mono mt-0.5">
            {job.branch} @ {job.shortSha}{job.completedAt ? ` · ${relativeTime(job.completedAt)}` : ''}
          </p>
          <p className="text-xs text-on-error-container font-mono mt-2 break-words">{headline}</p>
          {details && (
            <>
              <button onClick={() => setOpen((v) => !v)} className="mt-2 flex items-center gap-1 text-caption font-mono text-secondary hover:underline">
                <Icon name={open ? 'expand_less' : 'expand_more'} size={14} />
                {open ? 'Hide details' : 'Show details'}
              </button>
              {open && (
                <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-white border border-outline-variant p-3 text-caption font-mono text-on-surface-variant whitespace-pre-wrap">{details}</pre>
              )}
            </>
          )}
        </div>
        {isAdmin && (
          <button
            onClick={onRerun}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors flex-shrink-0 font-mono text-caption font-bold tracking-[0.04em]"
          >
            <Icon name="replay" size={14} />
            Re-run
          </button>
        )}
      </div>
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
  project, commits, commitsLoading, versions, submitting, defaultSha, onClose, onStart,
}: {
  project: Project
  commits?: Commit[]
  commitsLoading: boolean
  versions?: Version[]
  submitting: boolean
  defaultSha?: string
  onClose: () => void
  onStart: (body: StartJobInput) => void
}) {
  const cs = commits ?? []
  const [commitSha, setCommitSha] = useState(defaultSha ?? cs[0]?.sha ?? '')
  // Commits may still be loading when the modal opens (the commit sync/clone is
  // slow), so useState's initializer ran with an empty list. Adopt the default
  // commit as soon as the list arrives — otherwise Start stays disabled until
  // the user closes and reopens the modal.
  useEffect(() => {
    if (!commitSha && commits?.length) setCommitSha(defaultSha ?? commits[0].sha)
  }, [commitSha, commits, defaultSha])
  const branch = cs.find((c) => c.sha === commitSha)?.branch || cs[0]?.branch || project.defaultBranch || 'main'
  const [referenceId, setReferenceId] = useState('')
  const [versionName, setVersionName] = useState(() => suggestNextVersion(versions))

  // Advanced options (docs/ui-mockups/project-detail.html): which components to analyze - every
  // one ticked to start - and Skip LLM. The modal mounts on each open, so every run starts from
  // these defaults.
  const layers = project.architectureLayers
  const [advOpen, setAdvOpen] = useState(false)
  const [ticked, setTicked] = useState(() => new Set(allKeys(layers)))
  const [skipLlm, setSkipLlm] = useState(false)
  const everyComp = allKeys(layers)
  const total = everyComp.length
  const tickedCount = everyComp.filter((k) => ticked.has(k)).length
  const scope = scopeOf(layers, ticked)
  // A project with no component has nothing to tick; the API refuses its run with the reason.
  const nothingTicked = total > 0 && scope === null
  // On the Advanced options row, every option that is not its default: a narrowed run is never hidden.
  const changed = [
    ...(total > 0 && tickedCount < total ? [`${tickedCount} of ${total} components`] : []),
    ...(skipLlm ? ['Skip LLM'] : []),
  ]

  const refVersions = (versions ?? []).filter((v): v is Version & { id: string } => !!v.id)

  function submit() {
    if (!commitSha || nothingTicked) return
    onStart({
      commit_sha: commitSha,
      version_tag: versionName.trim() || undefined,
      reference_version_id: referenceId || undefined,
      // Every component ticked is the whole project: no scope, as before.
      scope: scope && scope.type !== 'project' ? scope : undefined,
      no_llm: skipLlm || undefined,
    })
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[rgba(4,22,39,.55)]" onClick={onClose}>
      <div className={cn('bg-white rounded-2xl w-full mx-4 flex flex-col max-h-[calc(100vh-32px)] shadow-[0_24px_64px_rgba(4,22,39,.28)]', advOpen ? 'max-w-[880px]' : 'max-w-[468px]')} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className="flex-shrink-0 px-6 pt-6 pb-5 flex items-start justify-between">
          <div>
            <h3 className="text-on-surface font-semibold font-sans text-[17px] leading-[1.25]">Run Analysis</h3>
            <p className={cn('text-on-surface-variant mt-1', FIELD_LABEL)}>Analyze a commit and save it as a named version.</p>
          </div>
          <button onClick={onClose} className="w-8 h-8 flex items-center justify-center rounded-xl hover:bg-surface-container transition-colors text-on-surface-variant flex-shrink-0 -mt-1 -mr-2">
            <Icon name="close" size={19} />
          </button>
        </div>

        {/* Body: the run, and - once Advanced options is opened - a second column. Header and
            footer stay put; the left column scrolls if it must, on the right only the tree. */}
        <div className={cn('flex-auto min-h-0 grid grid-rows-[minmax(0,1fr)] border-t border-surface-container-low', advOpen ? 'h-[580px] grid-cols-2' : 'grid-cols-1')}>
          <div className="min-h-0 overflow-y-auto overscroll-contain px-6 py-5 space-y-4">
            {/* Source card */}
            <div className="rounded-xl border border-outline-variant overflow-hidden">
              <div className="flex items-center gap-2.5 px-4 py-2.5 bg-surface-container-low border-b border-outline-variant">
                <Icon name="alt_route" size={14} className="text-on-surface-variant" />
                <span className={cn('text-on-surface-variant', FIELD_LABEL)}>Branch</span>
                <span className="font-mono text-xs font-bold text-on-surface">{branch}</span>
                <span className="ml-auto text-on-surface-variant text-label opacity-50 tracking-[.04em] font-mono">FIXED</span>
              </div>
              <div className="px-4 py-3">
                <label className={cn('text-on-surface-variant block mb-2', FIELD_LABEL)}>Commit</label>
                {cs.length === 0 ? (
                  <p className="text-on-surface-variant text-xs font-mono flex items-center gap-1.5">
                    {commitsLoading && <Icon name="progress_activity" size={13} className="animate-spin" />}
                    {commitsLoading ? 'Loading commits…' : 'No commits available to analyze yet.'}
                  </p>
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

            {/* Advanced options: opens the second column */}
            <button type="button" onClick={() => setAdvOpen((v) => !v)}
              className={cn('w-full flex items-center gap-2 pl-3 pr-2.5 py-[9px] border rounded-xl text-left transition-colors',
                advOpen ? 'border-secondary bg-surface text-secondary' : 'border-outline-variant bg-white text-on-surface-variant hover:border-secondary hover:text-secondary')}>
              <Icon name="tune" size={16} />
              <span className="flex-shrink-0 font-mono text-xs font-semibold">Advanced options</span>
              <span title={changed.join(' · ') || 'Every component, LLM on'}
                className={cn('ml-auto min-w-0 truncate px-1.5 rounded-[3px] font-mono text-label font-semibold',
                  nothingTicked ? 'bg-error-container text-error' : changed.length ? 'bg-surface-container text-secondary' : 'bg-surface-container-low text-outline')}>
                {changed.length ? changed.join(' · ') : 'Defaults'}
              </span>
              <Icon name={advOpen ? 'chevron_left' : 'chevron_right'} size={18} />
            </button>

            {/* Warning */}
            <div className="flex items-center gap-2.5 rounded-xl px-4 py-3 bg-[#f0f4ff] border border-[#c7d8ff]">
              <Icon name="schedule" size={15} className="flex-shrink-0 text-secondary" />
              <p className="text-[#0b2e6b] text-caption">Analysis runs server-side and can take <strong>several hours</strong> — safe to navigate away.</p>
            </div>
          </div>

          {advOpen && (
            <div className="min-h-0 flex flex-col px-6 py-5 bg-surface border-l border-surface-container">
              <ScopeTree layers={layers} ticked={ticked} onChange={setTicked} />
              <div className="flex-shrink-0 flex flex-col gap-3 mt-3.5 pt-3.5 border-t border-surface-container">
                {/* Skip LLM: the job's no_llm */}
                <label className="flex items-start gap-3 cursor-pointer group">
                  <input type="checkbox" checked={skipLlm} onChange={(e) => setSkipLlm(e.target.checked)} className="mt-0.5 rounded border-outline-variant text-secondary flex-shrink-0 w-[15px] h-[15px]" />
                  <div>
                    <span className="text-on-surface text-xs group-hover:text-secondary transition-colors">Skip LLM</span>
                    <p className="text-on-surface-variant mt-0.5 text-caption">Faster: the LLM steps are skipped. Use it to check structure, not wording.</p>
                  </div>
                </label>
                {/* Pause after Phase 1 — the server does not act on it yet: a run goes through all
                    four phases, and there is no function-visibility editor to pause for. */}
                <label className="flex items-start gap-3 cursor-not-allowed opacity-60">
                  <input type="checkbox" checked={false} disabled readOnly className="mt-0.5 rounded border-outline-variant text-secondary flex-shrink-0 w-[15px] h-[15px]" />
                  <div>
                    <span className="text-on-surface text-xs">Pause after Phase 1 to review function visibility</span>
                    <p className="text-on-surface-variant mt-0.5 text-caption">Not available yet — a run goes through all four phases without stopping.</p>
                  </div>
                </label>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex-shrink-0 px-6 py-4 border-t border-outline-variant flex items-center justify-between">
          <button onClick={onClose} className="px-4 py-2 text-on-surface-variant hover:bg-surface-container rounded-lg transition-colors text-sm">Cancel</button>
          <button onClick={submit} disabled={!commitSha || submitting || nothingTicked} title={nothingTicked ? 'Tick at least one component in Advanced options' : undefined}
            className="flex items-center gap-2 px-5 py-2.5 bg-secondary text-on-secondary rounded-xl transition-colors disabled:opacity-60 font-mono text-xs font-bold tracking-[.04em]">
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
  { key: 'SWE.4', label: 'Unit Test Specification' },
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
          {/* Always render all 5 ASPICE process rows. A process with no real
              generated document for the selected version renders as a distinct,
              muted, non-clickable "Not generated yet" row — clearly set apart
              from rows that actually have documents. */}
          {PROCESSES.map((p) => {
            const docs = documents.filter((d) => d.process === p.key)
            const total = docs.length

            if (total === 0) {
              return (
                <tr key={p.key} className="border-b border-outline-variant last:border-0">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-2.5 opacity-60">
                      <span className="font-mono text-caption font-bold text-on-surface-variant bg-surface-container px-2 py-0.5 rounded-[5px] flex-shrink-0">{p.key}</span>
                      <div>
                        <div className="text-body font-medium text-on-surface-variant leading-[1.3]">{p.label}</div>
                        <div className="text-caption text-outline">0 docs</div>
                      </div>
                    </div>
                  </td>
                  <td className="px-4 py-3" colSpan={2}>
                    <span className="text-caption text-outline-variant italic">Not generated yet</span>
                  </td>
                  <td className="px-3 py-2" />
                </tr>
              )
            }

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
  const downloadDoc = useDownloadDoc(projectId)
  const open = (doc: Document) => go(`/projects/${projectId}/documents/${doc.id}`)
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
              <tr key={doc.id} className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors cursor-pointer" onClick={() => open(doc)}>
                <td className="px-5 py-[13px]">
                  <div className="text-body font-medium text-on-surface leading-[1.3]">{doc.name}</div>
                  <div className="text-caption text-outline mt-0.5">{doc.subtitle ?? doc.process}</div>
                </td>
                <td className="px-4 py-[13px]"><span className="font-mono text-caption font-bold text-secondary bg-surface-container px-2 py-0.5 rounded-[5px]">{doc.process}</span></td>
                <td className="px-4 py-[13px]"><DocStatusPill status={doc.status} /></td>
                <td className="px-4 py-[13px] font-mono text-caption text-on-surface-variant">{doc.due ?? '—'}</td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1">
                    <button onClick={(e) => { e.stopPropagation(); open(doc) }} title="Open" className="flex items-center justify-center w-7 h-7 border border-[#e2e3e8] rounded-md bg-white text-outline cursor-pointer"><Icon name="open_in_new" size={14} /></button>
                    <button onClick={(e) => { e.stopPropagation(); void downloadDoc(doc.id, docxFileName(doc)) }} title="Download" className="flex items-center justify-center w-7 h-7 border border-[#e2e3e8] rounded-md bg-white text-outline cursor-pointer"><Icon name="download" size={14} /></button>
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

function FunctionVisibilityCard({ projectId, job, latestVersion }: { projectId: string; job?: AnalysisJob | null; latestVersion: string }) {
  // Counts from the latest finished run's function list (`GET …/jobs/{id}/functions`). There is
  // no editor to hide functions yet, so Manage is shown as unavailable rather than doing nothing.
  const finished = job?.status === 'complete' ? job : undefined
  const { data, isLoading } = useJobFunctions(projectId, finished?.id)
  const summary = data?.summary
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <div>
          <Text as="h2" variant="heading" className="text-on-surface">Function Visibility</Text>
          <Text as="p" variant="caption" className="font-mono mt-0.5">
            {summary
              ? `${summary.hidden} of ${summary.total} functions hidden from DOCX`
              : finished && isLoading ? 'Loading…' : 'No finished run to count yet'}
          </Text>
        </div>
        <button
          disabled
          title="Not available yet — there is no editor to hide functions"
          className="flex items-center gap-1 px-3 py-1.5 border border-outline-variant rounded-lg text-secondary font-mono text-caption opacity-50 cursor-not-allowed"
        >
          Manage<Icon name="arrow_forward" size={14} />
        </button>
      </div>
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon name={summary?.hidden ? 'visibility_off' : 'visibility'} size={14} className={summary?.hidden ? 'text-error' : 'text-on-surface-variant'} />
          <span className={cn('font-mono text-xs', summary?.hidden ? 'text-error' : 'text-on-surface-variant')}>{summary ? `${summary.hidden} hidden` : '—'}</span>
        </div>
        <span className="text-on-surface-variant font-mono text-caption">Last: {latestVersion}</span>
      </div>
    </div>
  )
}

// Placeholder activity feeds (no activity/audit endpoint yet — see INTEGRATION_NOTES).
type LastAction = { icon: string; color: string; text: string; time: string }

/** What happened last, from what the server does record: the latest job and the versions.
 *  (There is no activity log to read reviews and assignments from.) */
function lastActions(job: AnalysisJob | null | undefined, versions: Version[] | undefined): LastAction[] {
  const out: LastAction[] = []
  if (job && ['queued', 'running', 'paused'].includes(job.status)) {
    out.push({ icon: 'play_circle', color: 'text-secondary', text: `Analysis running${job.versionTag ? ` — ${job.versionTag}` : ''}`, time: relativeTime(job.startedAt) })
  } else if (job?.status === 'failed') {
    out.push({ icon: 'error', color: 'text-error', text: `Analysis failed${job.versionTag ? ` — ${job.versionTag}` : ''}`, time: relativeTime(job.completedAt) })
  } else if (job?.status === 'cancelled') {
    out.push({ icon: 'cancel', color: 'text-outline', text: `Analysis cancelled${job.versionTag ? ` — ${job.versionTag}` : ''}`, time: relativeTime(job.completedAt) })
  }
  for (const v of (versions ?? []).slice(0, 5)) {
    const approved = v.status === 'approved' || v.status === 'complete'
    out.push({
      icon: approved ? 'check_circle' : v.status === 'in_review' ? 'rate_review' : 'sell',
      color: approved ? 'text-[#00a572]' : v.status === 'in_review' ? 'text-amber' : 'text-outline',
      text: `${v.tag} generated from ${v.branch} @ ${v.shortSha}${approved ? ' — approved' : v.status === 'in_review' ? ' — in review' : ''}`,
      time: v.date,
    })
  }
  return out
}

function LastActionsCard({ job, versions }: { job?: AnalysisJob | null; versions?: Version[] }) {
  const actions = lastActions(job, versions)
  return (
    <div className="bg-white border border-outline-variant rounded-xl overflow-hidden flex-1 flex flex-col">
      <div className="px-4 py-3.5 border-b border-outline-variant">
        <Text as="h2" variant="heading" className="text-on-surface">Last Actions</Text>
      </div>
      <div className="flex-1 overflow-y-auto">
        {actions.length === 0 && (
          <p className="px-4 py-3 text-xs text-on-surface-variant">Nothing yet.</p>
        )}
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

function GeneratedContent({ project, documents, team, versions, job, isAdmin, projectId, go, selfAssign, meName, teamLoading }: {
  project: Project; documents?: Document[]; team?: TeamMember[]; versions?: Version[]; job?: AnalysisJob | null
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
          <FunctionVisibilityCard projectId={projectId} job={job} latestVersion={latestVersion} />
          <LastActionsCard job={job} versions={versions} />
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
  const { pageState, isLoading, viewVersion, viewVersionId, selectedCommit } = useProjectViewState(projectId ?? '')
  const { data: versions } = useVersions(projectId ?? '')
  // While a run is going, the Overview still shows the last finished version under the run card
  // (the picked one, when it is finished). It used to hide every document until the run ended.
  const running = pageState === 'running'
  const doneVersion = running
    ? (viewVersion && viewVersion.status !== 'draft' ? viewVersion : versions?.find((v) => v.status !== 'draft'))
    : undefined
  const contentVersionId = running ? doneVersion?.id : viewVersionId
  const { data: documents, isLoading: documentsLoading } = useDocuments(projectId ?? '', contentVersionId ? { versionId: contentVersionId } : undefined)
  const { data: team, isLoading: teamLoading } = useTeam(projectId ?? '')
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId ?? '')
  const { data: job } = useCurrentJob(projectId ?? '')
  const selfAssign = useSelfAssign(projectId ?? '')
  const startJob = useStartJob(projectId ?? '')
  const cancelJob = useCancelJob(projectId ?? '')
  const [runOpen, setRunOpen] = useState(false)
  useJobEvents(projectId ?? '', job?.id, job?.status)

  // Role is per-project (API's my_role → project.userRole).
  const isAdmin = project?.userRole === 'admin'

  // The commit shown in the empty/run states: the picker selection, else latest.
  const shownCommit = selectedCommit ?? commits?.[0]
  const startAnalysis = (body: StartJobInput) =>
    startJob.mutate(body, { onSuccess: () => setRunOpen(false) })

  const showContent = ['in_review', 'complete', 'stale'].includes(pageState) || (running && !!doneVersion)

  return (
    <div className="flex-1 overflow-y-auto bg-background">
      {/* The page's Subbar action. Without it a project that has a version had no way to start
          its next run: the only other buttons are on the empty state and the failure banner. */}
      {isAdmin && !isLoading && pageState !== 'running' && (
        <SubbarCta>
          <button
            onClick={() => setRunOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em]"
          >
            <Icon name="play_circle" size={14} fill />
            RUN ANALYSIS
          </button>
        </SubbarCta>
      )}
      <div className="px-6 py-6 max-w-[1280px] mx-auto">

        {/* ══ LOADING — gate the empty-state flash until the view state resolves ══ */}
        {isLoading && !project ? (
          <DashboardSkeleton />
        ) : (
          <>

        {/* ══ LAST RUN FAILED — the error, which no other state shows ══ */}
        {job?.status === 'failed' && pageState !== 'running' && (
          <FailedRunBanner job={job} isAdmin={isAdmin} onRerun={() => setRunOpen(true)} />
        )}

        {/* ══ THE RUN FINISHED, WITH WARNINGS — e.g. a component path the checkout did not have ══ */}
        {viewVersion && viewVersion.warnings.length > 0 && pageState !== 'running' && (
          <RunWarningsBanner key={viewVersion.id} version={viewVersion} />
        )}

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
                  Run analysis on <strong>{shownCommit ? `${shownCommit.branch} @ ${shownCommit.shortSha}` : 'the latest commit'}</strong> to generate each component's Detailed Design (SWE.3) and Unit Test Specification (SWE.4).
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
                {/* A queued job waits for a free worker: it must not look like it is running. */}
                <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 border-2 border-secondary border-t-transparent">
                  {job.status === 'queued'
                    ? <Icon name="hourglass_empty" size={16} className="text-on-primary-container" />
                    : <div className="animate-spin w-full h-full rounded-full border-2 border-secondary border-t-transparent" />}
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <p className="text-white font-semibold font-sans text-sm">
                      Analysis {job.status === 'paused' ? 'Paused' : job.status === 'queued' ? 'Queued' : 'Running'}
                    </p>
                    <span className={cn('font-mono text-micro font-bold text-white px-[7px] py-px rounded-[3px] uppercase tracking-[0.05em]', job.status === 'queued' ? 'bg-outline' : 'bg-secondary')}>
                      {job.status === 'queued' ? 'Queued' : 'Live'}
                    </span>
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
                  <p className="text-label font-mono text-outline uppercase tracking-[0.08em]">Started</p>
                  <p className="font-mono text-xs text-on-primary-container">{fmtStart(job.startedAt)}</p>
                </div>
                <div className="text-right">
                  <p className="text-label font-mono text-outline uppercase tracking-[0.08em]">Elapsed</p>
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
                    <Icon name={job.status === 'queued' ? 'hourglass_empty' : 'psychology'} size={14} className="text-secondary" />
                    <p className="text-on-surface font-mono text-caption">{job.currentActivity}</p>
                  </div>
                  <span className="text-secondary font-mono text-xs font-medium">{job.phasePct}%</span>
                </div>
                {/* No detail and no estimate: no row (it showed a lone "—"). */}
                {(() => {
                  const hasRow = !!job.activityDetail || job.etaSeconds != null
                  return (
                    <>
                      <div className={cn('progress-track', hasRow && 'mb-2')}>
                        {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
                        <div className="progress-fill bg-secondary" style={{ width: `${job.phasePct}%` }} />
                      </div>
                      {hasRow && (
                        <div className="flex items-center justify-between gap-4">
                          <p className="text-on-surface-variant font-mono text-caption truncate">{job.activityDetail}</p>
                          {job.etaSeconds != null && (
                            <p className="text-outline font-mono text-caption flex-shrink-0">Est. ~{fmtEta(job.etaSeconds)} remaining</p>
                          )}
                        </div>
                      )}
                    </>
                  )
                })()}
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
        {running && doneVersion && project && (
          <p className="mb-3 flex items-center gap-1.5 font-mono text-caption text-on-surface-variant">
            <Icon name="history" size={14} />
            Showing <span className="text-on-surface font-semibold">{doneVersion.tag}</span>
            {job?.versionTag ? <> while <span className="text-secondary">{job.versionTag}</span> is being generated</> : null}
          </p>
        )}
        {showContent && project && (
          documentsLoading && !documents ? (
            <DashboardSkeleton />
          ) : (
            <GeneratedContent
              project={project}
              documents={documents}
              team={team}
              versions={versions}
              job={job}
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
          commitsLoading={commitsLoading}
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
