import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CodeText, Icon } from '../../../components/ui'
import { relativeTime } from '../../../lib/format'
import { liveLogsHref } from '../../../lib/liveLogs'
import { useAuthStore } from '../../../store/auth'
import type { AnalysisJob, Version } from '../../../types'
import { failureParts } from '../helpers'

/* ─── The run that made the version on screen warned about something ─── */
// A path the checkout did not have (of a component with other files), a dictionary the run went
// without: the run still finished, so nothing else says so - and its documents lack those.
export function RunWarningsBanner({ version }: { version: Version }) {
  const [open, setOpen] = useState(false)
  const n = version.warnings.length
  const shown = open ? version.warnings : version.warnings.slice(0, 3)
  return (
    <div role="status" className="mb-6 rounded-xl border border-amber bg-state-warn-bg px-5 py-4">
      <div className="flex items-start gap-3">
        <Icon name="warning" size={20} fill className="flex-shrink-0 text-caution mt-0.5" />
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
export function FailedRunBanner({ projectId, job, isAdmin, onRerun }: {
  projectId: string; job: AnalysisJob; isAdmin: boolean; onRerun: () => void
}) {
  const [open, setOpen] = useState(false)
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  // The headline and the engine's reasons read as text, their `paths` as code; the log as a log.
  const { headline, reasons, log: details } = failureParts(job.errorMessage)
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
          <p className="text-xs text-on-error-container font-mono mt-2 break-words"><CodeText text={headline} /></p>
          {reasons.length > 0 && (
            <ul className="mt-1 ml-5 list-disc space-y-1">
              {reasons.map((r, i) => (
                <li key={i} className="text-xs text-on-error-container font-mono break-words"><CodeText text={r} /></li>
              ))}
            </ul>
          )}
          {details && (
            <>
              <button onClick={() => setOpen((v) => !v)} className="mt-2 flex items-center gap-1 text-caption font-mono text-secondary hover:underline">
                <Icon name={open ? 'expand_less' : 'expand_more'} size={14} />
                {open ? 'Hide details' : 'Show details'}
              </button>
              {open && (
                <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-surface-container-lowest border border-outline-variant p-3 text-caption font-mono text-on-surface-variant whitespace-pre-wrap">{details}</pre>
              )}
            </>
          )}
        </div>
        {/* Superusers: the run's lines in Live logs -- why it failed, before the details above */}
        {isSuperuser && (
          <Link to={liveLogsHref(projectId, job.versionId, job.id)} title="This run in Live logs"
            className="flex items-center gap-1 px-1 py-1.5 flex-shrink-0 text-caption font-semibold text-secondary hover:underline">
            <Icon name="terminal" size={14} />Logs
          </Link>
        )}
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
