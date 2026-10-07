import { useState, type ReactNode } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useResumeVersion, useVersionComponents } from '../../hooks/useVersionComponents'
import { useCancelJob } from '../../hooks/useJobs'
import { useVersionWordFiles, useWordFilesWatcher } from '../../hooks/useWordFiles'
import { Button, Icon } from '../ui'
import { cn } from '../../lib/cn'
import { relativeTime } from '../../lib/format'
import { runScope, useLogsPanel } from '../../store/logsPanel'
import { useAuthStore } from '../../store/auth'
import { generationBannerShown, generationSummary, type GenerationRow } from '../../lib/versionComponents'
import { wordFilesRow } from '../../lib/wordFiles'
import type { ArchLayer, VersionJob } from '../../types'
import { WordFilesRow } from '../wordfiles/WordFilesRow'
import { ComponentsDrawer } from './ComponentsDrawer'
import { StopRunDialog } from './StopRunDialog'

/* Staged generation in one row (docs/ui-mockups/project-detail.html `#gen-banner`): shown only
   while a component of the version has no documents, a run is making them or stopped before it
   finished; gone once every one has its documents. "View components" opens the Components drawer
   in place (`?components=1` opens it too). The Overview's row says what the run is doing and when
   it started, and an admin's Stop; the Documents page's (`compact`) keeps it short. A second row,
   under a divider, says which Word files are out of date — R9 `outOfDate`: corrections, or a layer
   added since — and offers the update this role may start (`WordFilesRow`; documents.html
   paintGenBanner). The card shows while either row has something to say. The end of an update is
   said here, once for the page (the toast, the bell, a download that waited for it). */

const ICON: Record<GenerationRow['kind'], { name: string; tone: string }> = {
  running: { name: 'autorenew', tone: 'text-secondary animate-spin' },
  stopped: { name: 'warning', tone: 'text-warn' },
  missing: { name: 'widgets', tone: 'text-on-surface-variant' },
}
const BAR: Record<GenerationRow['kind'], string> = {
  running: 'bg-secondary', stopped: 'bg-amber', missing: 'bg-success',
}

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

export function GenerationBanner({ projectId, versionId, versionTag, isAdmin, layers, compact, needsModel, className }: {
  projectId: string
  versionId: string
  versionTag?: string
  isAdmin: boolean
  /** The project's architecture (the drawer's groups when the API names none). */
  layers?: ArchLayer[]
  /** The Documents page: no activity, start time or Stop. */
  compact?: boolean
  /** A version with no documents yet: shown only when it has a model to make them from. */
  needsModel?: boolean
  className?: string
}) {
  const [pollUntil, setPollUntil] = useState(0)
  const { data } = useVersionComponents(projectId, versionId, pollUntil)
  const cancel = useCancelJob(projectId)
  const [stopping, setStopping] = useState(false)
  const [opened, setOpened] = useState(false)
  const resume = useResumeVersion(projectId, versionId)
  const [showCommand, setShowCommand] = useState(false)
  const [params, setParams] = useSearchParams()
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  const openLogs = useLogsPanel((s) => s.openLogs)
  const deepLink = params.get('components') === '1'

  // Word files (R9): which are out of date, an update under way, the end of one.
  const wf = useVersionWordFiles(projectId, versionId, versionTag ?? '')
  useWordFilesWatcher(projectId, versionId, wf.readiness, { meId: wf.meId, words: wf.words })
  const wordRow = wordFilesRow({
    readiness: wf.readiness, readinessFailed: wf.readinessFailed, docs: wf.docs, isAdmin, meId: wf.meId,
    myDocIds: wf.myDocIds, words: wf.words,
  })

  const summary = generationSummary(data)
  const shown = generationBannerShown(data, { needsModel })
  // The deep link opens it only where the banner shows; one opened here stays open as it changes.
  const open = (opened || (deepLink && shown)) && !!data && data.components.length > 0
  // Right after Generate / Stop the run has not taken the version yet: read again.
  const poll = (ms = 120_000) => setPollUntil(Date.now() + ms)
  function close() {
    setOpened(false)
    if (deepLink) {
      setParams((p) => { const next = new URLSearchParams(p); next.delete('components'); return next }, { replace: true })
    }
  }
  function stop(job: VersionJob) {
    // The run takes a few seconds to stop: keep reading until it has.
    cancel.mutate(job.id, { onSuccess: () => { setStopping(false); poll(60_000) } })
  }

  const wordRowEl = wordRow.kind === 'none' ? null : (
    <WordFilesRow projectId={projectId} versionId={versionId} state={wordRow} readiness={wf.readiness}
      docs={wf.docs} isAdmin={isAdmin} words={wf.words} />
  )
  if (!data || !summary) {
    return wordRowEl ? (
      <div className={cn('bg-surface-container-lowest border border-outline-variant rounded-xl', className)}>{wordRowEl}</div>
    ) : null
  }
  const { total, withDocs } = summary
  // An update is a run of the version too: the Word-files row says it, with its own progress.
  const runCommand = data.run?.alive ? data.run.command : data.job?.mode
  const row = shown && !(summary.row?.kind === 'running' && runCommand === 'reexport' && wordRow.kind === 'updating')
    ? summary.row : null
  const done = `${withDocs} of ${total}`
  // A run (or a web job) holds the version: Resume would be refused (409 VERSION_BUSY / RUN_ACTIVE).
  const resumeBusy = data.resumeAction === 'busy' || !!data.job

  let text: ReactNode = null
  let extra: ReactNode = null
  if (row?.kind === 'running') {
    const parts = [`${done} components done`]
    if (!compact && row.activity) parts.push(row.activity)
    if (!compact && row.startedAt) parts.push(`started ${relativeTime(row.startedAt)}`)
    text = <><b className="font-semibold text-on-surface">{row.verb}</b> · {parts.join(' · ')}</>
  } else if (row?.kind === 'stopped') {
    // Which components did not get their documents, and why: a failure's own words, else the stop.
    const names = row.cut.map((c) => c.id)
    const which = names.length > 2 ? `${names.slice(0, 2).join(', ')} +${names.length - 2} more` : names.join(', ')
    const failed = row.cut.find((c) => c.state === 'failed' && c.error)
    const reason = failed?.error?.split('\n')[0] ?? null
    const headline = row.at
      ? <><b className="font-semibold text-on-surface">Generation stopped</b> {relativeTime(row.at)} before it finished</>
      : row.cut.length === 1
        ? <b className="font-semibold text-on-surface">{names[0]} {row.cut[0].state === 'failed' ? 'failed' : 'stopped'}</b>
        : <b className="font-semibold text-on-surface">{plural(row.cutShort, 'component')} stopped or failed</b>
    text = (
      <>
        {headline}
        {row.at && which && <> · not made: {which}</>}
        {!row.at && row.cut.length > 1 && <> · {which}</>}
        {reason && <> · <span title={failed?.error ?? undefined}>{reason.length > 140 ? `${reason.slice(0, 140)}…` : reason}</span></>}
        {' · '}{done} done
      </>
    )
    extra = showCommand && (
      <code className="block mt-1 font-mono text-label text-state-warn bg-highlight px-1.5 py-0.5 rounded-[3px] break-all select-all">
        python analyzer.py resume --project-id {projectId} --version-id {versionId} --detach
      </code>
    )
  } else if (row?.kind === 'missing') {
    text = <><b className="font-semibold text-on-surface">{plural(row.missing, 'component')} {row.missing === 1 ? 'has' : 'have'} no documents yet</b> · {done} done</>
  }

  return (
    <>
      {(row || wordRowEl) && (
        <div role="status" aria-label="Generation" className={cn('bg-surface-container-lowest border border-outline-variant rounded-xl divide-y divide-hairline', className)}>
          {row && (
            <div className="flex items-center flex-wrap gap-x-3.5 gap-y-2 px-4 py-2.5">
              <Icon name={ICON[row.kind].name} size={18} className={cn('flex-shrink-0', ICON[row.kind].tone)} />
              <div className={cn('min-w-0 text-body text-on-surface-variant', compact ? 'flex-[1_1_220px]' : 'flex-[1_1_300px]')}>
                <p>{text}</p>
                {extra}
              </div>
              <span className="block w-[140px] h-1.5 rounded-full bg-track overflow-hidden flex-shrink-0" aria-hidden>
                {/* eslint-disable-next-line no-restricted-syntax -- the share done is data-driven */}
                <span className={cn('block h-full rounded-full', BAR[row.kind])} style={{ width: `${total ? (100 * withDocs) / total : 0}%` }} />
              </span>
              {/* Admins: carry the stopped run on from the web (POST .../resume) -- greyed out, with
                  the reason, while a run holds the version; the server command behind a link */}
              {isAdmin && row.kind === 'stopped' && data.resumeAction !== 'nothing' && (
                <>
                  <Button size="sm" onClick={() => resume.mutate(undefined, { onSuccess: () => poll() })}
                    disabled={resumeBusy || resume.isPending} loading={resume.isPending}
                    title={resumeBusy ? 'A run is at work on this version: Resume once it ends.' : 'Carry the run on from where it stopped'}
                    className="flex-shrink-0 h-auto py-1.5 rounded-[6px] whitespace-nowrap">
                    <Icon name="play_arrow" size={15} />Resume
                  </Button>
                  <button type="button" onClick={() => setShowCommand((v) => !v)}
                    className="flex-shrink-0 px-1 py-1.5 text-xs text-on-surface-variant hover:text-secondary hover:underline">
                    {showCommand ? 'Hide the command' : 'Run on the server'}
                  </button>
                </>
              )}
              <Button variant="outline" size="sm" onClick={() => setOpened(true)}
                className="flex-shrink-0 h-auto py-1.5 rounded-[6px] bg-surface-container-lowest whitespace-nowrap">
                View components
              </Button>
              {/* Superusers: what the run is doing, or why it stopped */}
              {isSuperuser && (row.kind === 'running' || row.kind === 'stopped') && (
                <button type="button" onClick={() => openLogs(runScope(projectId, versionId, data.job?.id, versionTag))} title="This run's lines, below"
                  className="flex-shrink-0 inline-flex items-center gap-1 px-1 py-1.5 text-xs font-semibold text-secondary hover:underline">
                  <Icon name="terminal" size={15} />Logs
                </button>
              )}
              {!compact && isAdmin && data.job && row.kind === 'running' && (
                <button
                  type="button"
                  onClick={() => setStopping(true)}
                  title="Stop making these documents? Components already finished keep their documents; the rest show as Stopped."
                  className="flex-shrink-0 px-1 py-1.5 text-xs font-semibold text-warn hover:underline"
                >
                  Stop
                </button>
              )}
            </div>
          )}
          {wordRowEl}
        </div>
      )}
      {open && (
        <ComponentsDrawer
          projectId={projectId}
          versionId={versionId}
          versionTag={versionTag}
          data={data}
          isAdmin={isAdmin}
          layers={layers}
          onClose={close}
          onStarted={() => poll()}
        />
      )}
      {stopping && data.job && (
        <StopRunDialog
          job={data.job}
          versionTag={versionTag}
          busy={cancel.isPending}
          onConfirm={() => data.job && stop(data.job)}
          onClose={() => setStopping(false)}
        />
      )}
    </>
  )
}
