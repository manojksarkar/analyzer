import { useId, useState } from 'react'
import { Icon, Modal } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { ScopeTree } from '../../../components/run/ScopeTree'
import { allKeys, keysWithDocuments, scopeOf } from '../../../lib/runScope'
import { useVersionComponents } from '../../../hooks/useVersionComponents'
import { useBaselinePreview } from '../../../hooks/useJobs'
import { useExportReadiness } from '../../../hooks/useReview'
import type { StartJobInput } from '../../../services/api'
import type { Commit, Project, Version } from '../../../types'
import { suggestNextVersion, versionNameProblem } from '../helpers'

/* ─── Run Analysis modal (matches project-detail.html) ─── */
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
  // The picked commit, else the default. Commits may still be loading when the modal opens (the
  // commit sync/clone is slow): the default follows the list as soon as it arrives, so Start
  // does not stay disabled until the modal is closed and reopened.
  const [pickedSha, setPickedSha] = useState('')
  const commitSha = pickedSha || defaultSha || cs[0]?.sha || ''
  const branch = cs.find((c) => c.sha === commitSha)?.branch || cs[0]?.branch || project.defaultBranch || 'main'
  const [referenceId, setReferenceId] = useState('')
  const [versionName, setVersionName] = useState(() => suggestNextVersion(versions))

  // Advanced options (docs/ui-mockups/project-detail.html): which components to analyze, and Skip
  // LLM. Every component is ticked to start; compared against a version (an incremental run), the
  // ones that version has documents for -- a whole project's run takes hours, and the demo makes a
  // few components. Ticks someone sets are kept for the version they were set under, so a list that
  // arrives later never overwrites them. The modal mounts on each open: every run starts afresh.
  const layers = project.architectureLayers
  const [advOpen, setAdvOpen] = useState(false)
  // A fresh run (NW-3): no baseline, so nothing is carried from an earlier version — no reused
  // text, no reviewer corrections. "Compare against" then has nothing to pick, and the scope starts
  // from every component, not the ones a version had documents for. For admins (every run is)
  // after an analyzer update, or to check a run. Ticked, it says how many corrections stay behind
  // in the version the run would have built on: the one picked, else the one the server would
  // pick (baseline preview); R9's `overrideCount` counts those in force.
  const [fresh, setFresh] = useState(false)
  const buildsOn = fresh ? '' : referenceId
  const [own, setOwn] = useState<{ ref: string; keys: Set<string> } | null>(null)
  const { data: baseline } = useVersionComponents(project.id, buildsOn || undefined)
  const baselineKeys = buildsOn && baseline ? keysWithDocuments(layers, baseline.components) : null
  const ticked = own && own.ref === buildsOn ? own.keys
    : baselineKeys && baselineKeys.size > 0 ? baselineKeys : new Set(allKeys(layers))
  const setTicked = (keys: Set<string>) => setOwn({ ref: buildsOn, keys })
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
    ...(fresh ? ['Fresh run'] : []),
  ]

  const refVersions = (versions ?? []).filter((v): v is Version & { id: string } => !!v.id)
  const { data: autoBase } = useBaselinePreview(project.id, commitSha, fresh && !referenceId)
  const baseId = fresh ? referenceId || autoBase || undefined : undefined
  const { data: baseReadiness } = useExportReadiness(project.id, baseId)
  const baseTag = refVersions.find((v) => v.id === baseId)?.tag
  const leftBehind = baseId && baseTag ? baseReadiness?.overrideCount ?? 0 : 0
  const nameProblem = versionNameProblem(versionName, versions)
  const nameHintId = useId()
  // Start says why it is off: the first thing still missing.
  const blocked = !commitSha ? 'Pick a commit to analyze.'
    : nameProblem ?? (nothingTicked ? 'Tick at least one component in Advanced options' : null)

  function submit() {
    if (blocked) return
    onStart({
      commit_sha: commitSha,
      version_tag: versionName.trim(),
      reference_version_id: buildsOn || undefined,
      // Every component ticked is the whole project: no scope, as before.
      scope: scope && scope.type !== 'project' ? scope : undefined,
      no_llm: skipLlm || undefined,
      mode: fresh ? 'full' : undefined,
    })
  }

  // ui/Modal: Esc and the close button close it, focus stays inside; a click beside it does not
  // (it threw the form away).
  return (
    <Modal
      open
      onClose={onClose}
      title="Run Analysis"
      description="Analyze a commit and save it as a named version."
      closeOnOutsideClick={false}
      className={cn('p-0 w-[calc(100%-32px)] flex flex-col max-h-[calc(100vh-32px)] shadow-[0_24px_64px_rgba(4,22,39,.28)]', advOpen ? 'max-w-[880px]' : 'max-w-[468px]')}
      headerClassName="flex-shrink-0 items-start mb-0 px-6 pt-6 pb-5"
    >
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
              <span className="ml-auto text-outline text-label tracking-[.04em] font-mono">FIXED</span>
            </div>
            <div className="px-4 py-3">
              <label className={cn('text-on-surface-variant block mb-2', FIELD_LABEL)}>Commit</label>
              {cs.length === 0 ? (
                <p className="text-on-surface-variant text-xs font-mono flex items-center gap-1.5">
                  {commitsLoading && <Icon name="progress_activity" size={13} className="animate-spin" />}
                  {commitsLoading ? 'Loading commits…' : 'No commits available to analyze yet.'}
                </p>
              ) : (
                <select value={commitSha} aria-label="Commit" onChange={(e) => setPickedSha(e.target.value)} className={cn('w-full rounded-lg px-3 py-2 text-on-surface bg-surface-container-lowest cursor-pointer border border-field', SELECT_CLS)}>
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
              <span className="text-label text-outline font-mono">OPTIONAL</span>
            </div>
            <select value={fresh ? '' : referenceId} disabled={fresh} aria-label="Compare against" onChange={(e) => setReferenceId(e.target.value)} className={cn('w-full border border-field rounded-lg px-3 py-2 text-on-surface bg-surface-container-lowest cursor-pointer disabled:cursor-not-allowed disabled:opacity-60', SELECT_CLS)}>
              <option value="">— None —</option>
              {refVersions.map((v) => (
                <option key={v.id} value={v.id}>{v.tag} · {v.shortSha} — {v.description}</option>
              ))}
            </select>
            <p className={cn('text-on-surface-variant mt-1.5', FIELD_LABEL)}>
              {fresh ? 'A fresh run builds on no earlier version.' : 'The version this run builds on. None: the newest earlier one.'}
            </p>
            {baselineKeys && baselineKeys.size > 0 && own?.ref !== buildsOn && (
              <p className={cn('text-secondary mt-1', FIELD_LABEL)}>
                Starts with the {baselineKeys.size} component{baselineKeys.size === 1 ? '' : 's'} {refVersions.find((v) => v.id === referenceId)?.tag ?? 'it'} has documents for.
              </p>
            )}
          </div>

          {/* Version name */}
          <div>
            <label className={cn('text-on-surface-variant block mb-2', FIELD_LABEL)}>Version name</label>
            <div className="relative">
              <Icon name="sell" size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant" />
              <input value={versionName} onChange={(e) => setVersionName(e.target.value)} type="text" placeholder="e.g. v1.3.0" autoComplete="off" spellCheck={false}
                aria-label="Version name" aria-invalid={nameProblem ? 'true' : undefined} aria-describedby={nameProblem ? nameHintId : undefined}
                className={cn('w-full border rounded-lg pl-9 pr-3 py-2.5 bg-surface-container-lowest font-mono text-body font-bold text-secondary tracking-[.03em] box-border',
                  nameProblem ? 'border-error' : 'border-field')} />
            </div>
            {nameProblem && <p id={nameHintId} className={cn('text-error mt-1.5', FIELD_LABEL)}>{nameProblem}</p>}
          </div>

          {/* Advanced options: opens the second column */}
          <button type="button" onClick={() => setAdvOpen((v) => !v)}
            className={cn('w-full flex items-center gap-2 pl-3 pr-2.5 py-[9px] border rounded-xl text-left transition-colors',
              advOpen ? 'border-secondary bg-surface text-secondary' : 'border-outline-variant bg-surface-container-lowest text-on-surface-variant hover:border-secondary hover:text-secondary')}>
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
          <div className="flex items-center gap-2.5 rounded-xl px-4 py-3 bg-tint border border-info-line">
            <Icon name="schedule" size={15} className="flex-shrink-0 text-secondary" />
            <p className="text-on-surface text-caption">Analysis runs server-side and can take <strong>several hours</strong> — safe to navigate away.</p>
          </div>
        </div>

        {advOpen && (
          <div className="min-h-0 flex flex-col px-6 py-5 bg-surface border-l border-surface-container">
            <ScopeTree layers={layers} ticked={ticked} onChange={setTicked} />
            <div className="flex-shrink-0 flex flex-col gap-3 mt-3.5 pt-3.5 border-t border-surface-container">
              {/* Skip LLM: the job's no_llm */}
              <label className="flex items-start gap-3 cursor-pointer group">
                <input type="checkbox" checked={skipLlm} onChange={(e) => setSkipLlm(e.target.checked)} className="mt-0.5 rounded border-field text-secondary flex-shrink-0 w-[15px] h-[15px]" />
                <div>
                  <span className="text-on-surface text-xs group-hover:text-secondary transition-colors">Skip LLM</span>
                  <p className="text-on-surface-variant mt-0.5 text-caption">Faster: the LLM steps are skipped. Use it to check structure, not wording.</p>
                </div>
              </label>
              {/* Fresh run: the job's mode "full" */}
              <label className="flex items-start gap-3 cursor-pointer group">
                <input type="checkbox" checked={fresh} onChange={(e) => setFresh(e.target.checked)} className="mt-0.5 rounded border-field text-secondary flex-shrink-0 w-[15px] h-[15px]" />
                <div>
                  <span className="text-on-surface text-xs group-hover:text-secondary transition-colors">Fresh run</span>
                  <p className="text-on-surface-variant mt-0.5 text-caption">Rebuilds everything with this analyzer version. Use after an analyzer update, or to check a run.</p>
                  {leftBehind > 0 && (
                    <p className="text-warn mt-1 text-caption font-semibold">
                      Not carried over: {leftBehind} correction{leftBehind === 1 ? '' : 's'} in {baseTag}. They stay there.
                    </p>
                  )}
                </div>
              </label>
              {/* No "Pause after Phase 1" (2026-11-03): never used, and no function-visibility
                  editor to pause for (BACKLOG WA-1). */}
            </div>
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 px-6 py-4 border-t border-outline-variant flex items-center justify-between">
        <button onClick={onClose} className="px-4 py-2 text-on-surface-variant hover:bg-surface-container rounded-lg transition-colors text-sm">Cancel</button>
        <button onClick={submit} disabled={!!blocked || submitting} title={blocked ?? undefined}
          className="flex items-center gap-2 px-5 py-2.5 bg-action text-on-secondary rounded-xl transition-colors disabled:opacity-60 font-mono text-xs font-bold tracking-[.04em]">
          <Icon name="rocket_launch" size={16} fill />
          {submitting ? 'STARTING…' : 'START ANALYSIS'}
        </button>
      </div>
    </Modal>
  )
}
