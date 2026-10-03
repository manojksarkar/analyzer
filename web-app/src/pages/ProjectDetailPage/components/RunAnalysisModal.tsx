import { useEffect, useState } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { ScopeTree } from '../../../components/run/ScopeTree'
import { allKeys, scopeOf } from '../../../lib/runScope'
import type { StartJobInput } from '../../../services/api'
import type { Commit, Project, Version } from '../../../types'

/* ─── Run Analysis modal (matches project-detail.html) ─── */
function suggestNextVersion(versions?: Version[]): string {
  if (!versions || versions.length === 0) return 'v1.0.0'
  const m = versions[0].tag.match(/^v?(\d+)\.(\d+)\.(\d+)$/)
  return m ? `v${m[1]}.${parseInt(m[2], 10) + 1}.0` : ''
}

const SELECT_CLS = 'font-mono text-xs'
const FIELD_LABEL = 'text-caption font-mono'

export function RunAnalysisModal({
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
