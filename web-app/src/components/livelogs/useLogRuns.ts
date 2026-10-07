import { useEffect, useMemo, useState } from 'react'
import { useProjects } from '../../hooks/useProjects'
import { useAllProjectRuns } from '../../hooks/useVersionComponents'
import { useAuthStore } from '../../store/auth'
import { useLogsPanel } from '../../store/logsPanel'
import { runState, sortRuns } from './helpers'

/* What the Logs button and panel both need: every project's name, every run at work (or cut
   short), and whether one has gone quiet -- read once, shared through React Query's cache. */
export function useLogRuns() {
  const { data: projects } = useProjects()
  const projectIds = useMemo(() => (projects ?? []).map((p) => p.id), [projects])
  const all = useAllProjectRuns(projectIds)
  const names = useMemo(() => Object.fromEntries((projects ?? []).map((p) => [p.id, p.name])), [projects])
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [])
  const runs = sortRuns(all.runs)
  return {
    projects: projects ?? [],
    projectName: (id: string) => names[id] ?? id,
    runs,
    pending: all.pending || !projects,
    now,
    /** A run alive, but with no progress for 10 minutes: the button's amber dot. */
    quiet: runs.some(({ run }) => runState(run, now).tone === 'quiet'),
  }
}

/** The panel at full height takes the page's place: the layout hides its content meanwhile. */
export function useLogsTakeThePage(): boolean {
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  const full = useLogsPanel((s) => s.open && s.maximized)
  return isSuperuser && full
}
