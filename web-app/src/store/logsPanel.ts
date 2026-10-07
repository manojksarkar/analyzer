import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

/* The Logs panel (superusers): docked at the bottom of whatever page is open, so reading a run's
   lines never leaves the page. What it shows, its size and whether it is open last for the
   browser tab (sessionStorage), across pages. */

/** What the panel shows: one run (its version, or its job when it has no version any more), one
 *  project, or every project and the API. `label` names it in the Showing button. */
export type LogScope =
  | { kind: 'all' }
  | { kind: 'project'; project: string; label?: string }
  | { kind: 'version'; project: string; version: string; label?: string }
  | { kind: 'job'; project: string; job: string; label?: string }

/** A run's scope, for its Logs link: by version, or by job when the version is gone (a failed
 *  run's draft is removed). */
export function runScope(project: string, version: string | null | undefined, job: string | null | undefined,
  label?: string): LogScope {
  if (version) return { kind: 'version', project, version, label }
  if (job) return { kind: 'job', project, job, label }
  return { kind: 'project', project }
}

export const MIN_HEIGHT = 160
export const DEFAULT_HEIGHT = 300

interface LogsPanelState {
  open: boolean
  height: number
  maximized: boolean
  scope: LogScope
  /** Open it, on `scope` when given (a run's Logs link), else on what it showed last. */
  openLogs: (scope?: LogScope) => void
  close: () => void
  setScope: (scope: LogScope) => void
  setHeight: (height: number) => void
  toggleMax: () => void
}

/** Session storage that never throws (blocked storage: the panel lasts for the page only). */
const safeSession = createJSONStorage(() => ({
  getItem: (k: string) => { try { return sessionStorage.getItem(k) } catch { return null } },
  setItem: (k: string, v: string) => { try { sessionStorage.setItem(k, v) } catch { /* blocked */ } },
  removeItem: (k: string) => { try { sessionStorage.removeItem(k) } catch { /* blocked */ } },
}))

export const useLogsPanel = create<LogsPanelState>()(
  persist(
    (set) => ({
      open: false,
      height: DEFAULT_HEIGHT,
      maximized: false,
      scope: { kind: 'all' },
      openLogs: (scope) => set((s) => ({ open: true, scope: scope ?? s.scope })),
      close: () => set({ open: false }),
      setScope: (scope) => set({ scope }),
      setHeight: (height) => set({ height: Math.max(MIN_HEIGHT, Math.round(height)), maximized: false }),
      toggleMax: () => set((s) => ({ maximized: !s.maximized })),
    }),
    {
      name: 'logsPanel',
      storage: safeSession,
      partialize: (s) => ({ open: s.open, height: s.height, maximized: s.maximized, scope: s.scope }),
    },
  ),
)
