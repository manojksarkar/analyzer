import { useParams } from 'react-router-dom'
import { Icon } from '../ui'
import { cn } from '../../lib/cn'
import { useAuthStore } from '../../store/auth'
import { useLogsPanel, type LogScope } from '../../store/logsPanel'
import { useLogRuns } from './useLogRuns'
import { runWords } from './helpers'

/* The top bar's Logs button (superusers): opens the Logs panel on the page that is open, or closes
   it. In a project it shows that project's run at work, else the project; outside one, everything.
   An amber dot while a run has reported nothing for 10 minutes. */
export function LogsButton() {
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  if (!isSuperuser) return null
  return <Button />
}

function Button() {
  const { projectId } = useParams<{ projectId?: string }>()
  const open = useLogsPanel((s) => s.open)
  const openLogs = useLogsPanel((s) => s.openLogs)
  const close = useLogsPanel((s) => s.close)
  const { runs, quiet, projectName } = useLogRuns()

  function here(): LogScope {
    if (!projectId) return { kind: 'all' }
    const live = runs.find((r) => r.projectId === projectId && r.run.alive)
    return live
      ? { kind: 'version', project: projectId, version: live.run.versionId,
          label: `${projectName(projectId)} · ${live.run.versionTag} · ${runWords(live.run.command)}` }
      : { kind: 'project', project: projectId }
  }

  return (
    <button type="button" onClick={() => (open ? close() : openLogs(here()))} aria-pressed={open}
      title={quiet ? 'Logs -- a run has reported nothing for 10 minutes' : 'Logs'} aria-label="Logs"
      className={cn('relative p-2 rounded-lg transition-colors', open ? 'bg-tint' : 'hover:bg-surface-container')}>
      <Icon name="terminal" size={22} className={open ? 'text-secondary' : 'text-on-surface-variant'} />
      {quiet && <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-warn border-2 border-surface-container-lowest" aria-hidden />}
    </button>
  )
}
