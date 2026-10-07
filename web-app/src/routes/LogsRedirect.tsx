import { useEffect } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuthStore } from '../store/auth'
import { useLogsPanel } from '../store/logsPanel'

/* `/admin/logs`, where Live logs was a page: the logs are a panel now, on whatever page is open.
   An old link opens the panel on everything (superusers) and lands on Projects. */
export function LogsRedirect() {
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  const openLogs = useLogsPanel((s) => s.openLogs)
  useEffect(() => { if (isSuperuser) openLogs({ kind: 'all' }) }, [isSuperuser, openLogs])
  return <Navigate to="/projects" replace />
}
