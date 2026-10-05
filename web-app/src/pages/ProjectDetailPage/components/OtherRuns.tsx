import { Icon } from '../../../components/ui'
import { useProjectRuns } from '../../../hooks/useVersionComponents'
import { relativeTime } from '../../../lib/format'
import type { ProjectRun } from '../../../types'

/* The project's other runs, at work now or cut short — whichever front door started them: a web
   job the Overview does not show (a Components → Generate, a re-export), or `analyzer.py
   generate | export | reexport | resume` on the server (`--detach`), which the Overview could not
   see at all (GET /projects/{pid}/runs). Read again every 15 s while one is alive. */

function progress(r: ProjectRun): string {
  if (!r.stage) return ''
  const pct = r.total ? Math.floor((100 * (r.done ?? 0)) / r.total) : null
  return ` — stage ${r.stage.replace(/-/g, ' ')}${r.total ? ` ${r.done ?? 0}/${r.total}${pct !== null ? ` (${pct}%)` : ''}` : ''}`
}

export function OtherRuns({ projectId, exceptVersionId }: {
  projectId: string
  /** The version whose web job the Overview shows already (its running card). */
  exceptVersionId?: string | null
}) {
  const { data } = useProjectRuns(projectId)
  const runs = (data ?? []).filter((r) => r.versionId !== exceptVersionId)
  if (!runs.length) return null
  return (
    <div className="mb-6 space-y-2" aria-label="Other runs">
      {runs.map((r) => {
        const what = `${r.command || 'run'} into ${r.versionTag}`
        return r.alive ? (
          <div key={r.versionId} role="status" className="flex items-center gap-3 px-4 py-3 rounded-xl border border-outline-variant bg-white">
            <Icon name="autorenew" size={16} className="text-secondary animate-spin flex-shrink-0" />
            <p className="flex-1 min-w-0 font-mono text-caption text-on-surface">
              <b className="font-semibold">Running {what}</b>{progress(r)}
              {r.startedAt ? <span className="text-outline"> · started {relativeTime(r.startedAt)}</span> : null}
              {r.host ? <span className="text-outline"> · on {r.host}</span> : null}
            </p>
          </div>
        ) : (
          <div key={r.versionId} role="status" className="flex items-start gap-3 px-4 py-3 rounded-xl border bg-[#fffbeb] border-[#fcd34d]">
            <Icon name="warning" size={16} className="text-[#b45309] flex-shrink-0 mt-px" />
            <div className="min-w-0">
              <p className="font-mono text-caption text-[#92400e]">
                <b className="font-semibold">Stopped:</b> {what} stopped
                {r.progressAt || r.startedAt ? ` ${relativeTime(r.progressAt ?? r.startedAt)}` : ''} before it finished
                {progress(r)}. Resume it on the server:
              </p>
              <code className="block mt-1 font-mono text-label text-[#92400e] bg-[#fef3c7] px-1.5 py-0.5 rounded-[3px] break-all select-all">
                python analyzer.py resume --project-id {projectId} --version-id {r.versionId} --detach
              </code>
            </div>
          </div>
        )
      })}
    </div>
  )
}
