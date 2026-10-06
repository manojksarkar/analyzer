import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { HomeTopbar } from '../../components/shell/HomeTopbar'
import { Icon } from '../../components/ui'
import { useLiveLogs } from '../../hooks/useLiveLogs'
import { useProjects, useVersions, useVersionTags } from '../../hooks/useProjects'
import { useAllProjectRuns } from '../../hooks/useVersionComponents'
import { cn } from '../../lib/cn'
import { LogFilters } from './components/LogFilters'
import { LogRow, type LogPick } from './components/LogRow'
import { RunsRail } from './components/RunsRail'
import { filtersFromParams, matches, paramsFromFilters, serverFilters, sortRuns, type PageFilters } from './helpers'

/* Live logs, superusers only (docs/spec/LIVE_LOGS_SPEC.md; route /admin/logs): the API's and every
   engine run's lines in one list, newest at the bottom, new ones as they are written. Reached from
   the account menu (every project) or a run's Logs link (that run: `?job=…`, or `?project=&version=`).
   The filters live in the address, so a run's logs can be shared as a link. */

export function LiveLogsPage() {
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => filtersFromParams(params), [params])
  const logs = useLiveLogs(useMemo(() => serverFilters(filters), [filters]))

  // Names: the API sends ids; the projects are already read, the version tags on demand.
  const { data: projects } = useProjects()
  const names = useMemo(() => Object.fromEntries((projects ?? []).map((p) => [p.id, p.name])), [projects])
  const projectName = useCallback((id: string) => names[id] ?? id, [names])
  const seenKey = useMemo(() => [...new Set(
    logs.rows.map((r) => r.project).concat(filters.project ?? null).filter((p): p is string => !!p),
  )].slice(0, 12).join(','), [logs.rows, filters.project])
  const tags = useVersionTags(useMemo(() => (seenKey ? seenKey.split(',') : []), [seenKey]))
  const tagsKey = JSON.stringify(tags)
  const versionTag = useMemo(() => {
    const t: Record<string, string> = JSON.parse(tagsKey)
    return (id: string) => t[id] ?? id
  }, [tagsKey])
  const { data: versions } = useVersions(filters.project ?? '')

  // Runs: every project's, or the picked one's.
  const projectIds = useMemo(() => (projects ?? []).map((p) => p.id), [projects])
  const allRuns = useAllProjectRuns(projectIds)
  const runs = sortRuns(allRuns.filter((r) => !filters.project || r.projectId === filters.project))
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 30_000)
    return () => window.clearInterval(t)
  }, [])

  // Client controls: they only change what is drawn.
  const [query, setQuery] = useState('')
  const [follow, setFollow] = useState(true)
  const [pausedAt, setPausedAt] = useState(0)
  const [clearedAt, setClearedAt] = useState(0)
  const [open, setOpen] = useState<Set<number>>(() => new Set())
  const shown = useMemo(
    () => logs.rows.filter((r) => r.seq > clearedAt && matches(r, query)),
    [logs.rows, clearedAt, query],
  )
  const unseen = follow ? 0 : shown.filter((r) => r.seq > pausedAt).length
  const oneRun = !!(filters.job || filters.version)
  // One run: its steps become dividers instead of a filter (the lines that start one).
  const stepStarts = useMemo(() => {
    const at = new Set<number>()
    let step = ''
    if (oneRun) {
      for (const r of shown) {
        if (r.source === 'engine' && r.step && r.step !== step) { step = r.step; at.add(r.seq) }
      }
    }
    return at
  }, [shown, oneRun])

  // A server filter replaces the address (the page reads it back): the tail is read again, and a
  // new stream opened.
  const setFilters = (next: Partial<PageFilters>) => {
    setClearedAt(0)
    setParams(paramsFromFilters({ ...filters, ...next }), { replace: true })
  }
  const pick = useCallback((p: LogPick) => {
    setClearedAt(0)
    setParams(paramsFromFilters({ ...filtersFromParams(params), project: p.project, version: p.version, job: p.job }), { replace: true })
  }, [params, setParams])
  const toggle = useCallback((seq: number) => setOpen((s) => {
    const n = new Set(s)
    if (!n.delete(seq)) n.add(seq)
    return n
  }), [])

  // Follow: stay at the newest line; scrolling up pauses it, the pill (or the switch) resumes it.
  const listRef = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = listRef.current
    if (el && follow) el.scrollTop = el.scrollHeight
  }, [shown, follow])
  const pause = () => { setFollow(false); setPausedAt(shown.at(-1)?.seq ?? 0) }
  const onScroll = () => {
    const el = listRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    if (atBottom && !follow) setFollow(true)
    else if (!atBottom && follow) pause()
  }

  if (logs.forbidden) {
    return (
      <Shell>
        <div className="flex-1 flex flex-col items-center justify-center text-center">
          <Icon name="lock" size={40} className="text-outline" />
          <h2 className="mt-3 text-lg font-semibold text-on-surface">Superusers only</h2>
          <p className="mt-1 text-body text-on-surface-variant">Live logs show every project's runs.</p>
          <Link to="/projects" className="mt-5 inline-flex items-center h-8 px-3 border border-outline-variant rounded-lg text-body text-on-surface hover:bg-surface-container">
            All projects
          </Link>
        </div>
      </Shell>
    )
  }

  const where = filters.project
    ? [projectName(filters.project), filters.version && versionTag(filters.version)].filter(Boolean).join(' · ')
    : ''
  return (
    <Shell>
      <Link to="/projects" className="inline-flex items-center gap-1 text-xs text-on-surface-variant hover:text-secondary self-start">
        <Icon name="arrow_back" size={15} />All projects
      </Link>
      <div className="flex items-center gap-3 mt-1">
        <h2 className="text-2xl font-semibold tracking-[-0.01em] text-on-surface">Live logs</h2>
        <Status status={logs.status} retryIn={logs.retryIn} onReconnect={logs.reconnect} />
      </div>
      <p className="mt-0.5 text-body text-on-surface-variant">
        {where || 'Every project’s runs and the API, newest at the bottom.'}
      </p>

      <div className="mt-4">
        <LogFilters
          filters={filters}
          onChange={setFilters}
          projects={(projects ?? []).map((p) => ({ value: p.id, label: p.name }))}
          versions={(versions ?? []).filter((v) => v.id).map((v) => ({ value: v.id as string, label: v.tag }))}
          query={query}
          onQuery={setQuery}
          follow={follow}
          onFollow={(on) => (on ? setFollow(true) : pause())}
          onClear={() => setClearedAt(logs.rows.at(-1)?.seq ?? 0)}
        />
      </div>

      <div className="flex-1 min-h-0 mt-4 flex bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
        <RunsRail
          runs={runs}
          selectedVersion={filters.version}
          scope={filters.project ? projectName(filters.project) : 'Every project'}
          now={now}
          projectName={projectName}
          onSelect={(r) => setFilters(r
            ? { project: r.projectId, version: r.run.versionId, job: undefined }
            : { version: undefined, job: undefined })}
        />
        <div className="flex-1 min-w-0 flex flex-col relative">
          <div className="h-8 flex-shrink-0 grid grid-cols-[94px_70px_minmax(0,1fr)] gap-x-3 items-center px-4 bg-surface-container-low border-b border-outline-variant font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline">
            <span>Time</span><span>Level</span><span>Message</span>
          </div>
          <div ref={listRef} onScroll={onScroll} className="flex-1 min-h-0 overflow-y-auto" aria-live="off">
            {logs.loading && <p className="px-4 py-14 text-center text-body text-outline">Reading the logs…</p>}
            {logs.error && !logs.loading && (
              <p className="px-4 py-14 text-center text-body text-outline">Could not read the logs: {logs.error.message}</p>
            )}
            {!logs.loading && !logs.error && !shown.length && (
              <p className="px-4 py-14 text-center text-body text-outline">
                {clearedAt && !query ? 'Cleared. New lines appear here as they arrive.' : 'No lines match. New ones appear here as they arrive.'}
              </p>
            )}
            {shown.map((r) => {
              const divider = stepStarts.has(r.seq) ? r.step : null
              return (
                <Fragment key={r.seq}>
                  {divider && (
                    <div className="flex items-center gap-2.5 px-4 pt-2.5 pb-1 font-mono text-label font-semibold uppercase tracking-[0.06em] text-secondary after:content-[''] after:flex-1 after:h-px after:bg-info-line">
                      {divider}
                    </div>
                  )}
                  <LogRow r={r} oneRun={oneRun} query={query} open={open.has(r.seq)} onToggle={toggle}
                    onPick={pick} projectName={projectName} versionTag={versionTag} />
                </Fragment>
              )
            })}
          </div>
          {unseen > 0 && (
            <button type="button" onClick={() => setFollow(true)}
              className="absolute left-1/2 -translate-x-1/2 bottom-12 inline-flex items-center gap-1.5 h-[30px] px-3.5 rounded-full bg-secondary text-on-secondary text-xs font-semibold shadow-[0_8px_24px_rgba(0,0,0,.25)]">
              <Icon name="arrow_downward" size={16} />{unseen} new line{unseen === 1 ? '' : 's'}
            </button>
          )}
          <div className="h-9 flex-shrink-0 flex items-center justify-between px-4 border-t border-outline-variant text-xs text-outline">
            <span>{shown.length.toLocaleString()} line{shown.length === 1 ? '' : 's'}</span>
            <span>Keeps the last {logs.cap.toLocaleString()}</span>
          </div>
        </div>
      </div>
    </Shell>
  )
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <HomeTopbar />
      <main className="flex-1 min-h-0 flex flex-col w-full max-w-[1480px] mx-auto px-6 pt-5 pb-6">{children}</main>
    </div>
  )
}

function Status({ status, retryIn, onReconnect }: {
  status: 'connecting' | 'live' | 'reconnecting' | 'stopped'
  retryIn: number | null
  onReconnect: () => void
}) {
  const tone = status === 'live' ? 'text-success' : status === 'reconnecting' ? 'text-warn' : 'text-on-surface-variant'
  const dot = status === 'live' ? 'bg-success' : status === 'reconnecting' ? 'bg-warn' : 'bg-outline'
  const text = status === 'live' ? 'Live'
    : status === 'reconnecting' ? (retryIn ? `Reconnecting in ${retryIn} s` : 'Reconnecting')
      : status === 'stopped' ? 'Stopped' : 'Connecting'
  return (
    <span role="status" className={cn('inline-flex items-center gap-1.5 text-xs font-medium', tone)}>
      <span className={cn('w-2 h-2 rounded-full', dot)} aria-hidden />
      {text}
      {status === 'stopped' && (
        <button type="button" onClick={onReconnect} className="ml-1 text-secondary hover:underline">Reconnect</button>
      )}
    </span>
  )
}
