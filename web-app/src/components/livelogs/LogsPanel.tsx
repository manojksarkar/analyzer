import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Icon } from '../ui'
import { cn } from '../../lib/cn'
import { useAuthStore } from '../../store/auth'
import { MIN_HEIGHT, useLogsPanel } from '../../store/logsPanel'
import { useLiveLogs, type LiveStatus } from '../../hooks/useLiveLogs'
import { useVersionTags } from '../../hooks/useProjects'
import type { LogSource } from '../../types'
import { LogRow } from './LogRow'
import { ScopePicker } from './ScopePicker'
import { useLogRuns } from './useLogRuns'
import { isOneRun, matches, serverFilters, type Show } from './helpers'

/* The Logs panel (superusers; docs/spec/LIVE_LOGS_SPEC.md): the API's and every engine run's lines,
   docked at the bottom of the page that is open -- reading a run's lines never leaves the page,
   so there is nothing to come back from. It opens from the top bar's Logs button or a run's Logs
   link, shows one run, one project or everything (the Showing button), resizes by its top edge,
   and takes the whole content area on request. Esc closes it. */

export function LogsPanel({ projectId }: { projectId?: string }) {
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  const open = useLogsPanel((s) => s.open)
  if (!isSuperuser || !open) return null
  return <OpenPanel projectId={projectId} />
}

function OpenPanel({ projectId }: { projectId?: string }) {
  const { height, maximized, scope, close, setScope, setHeight, toggleMax } = useLogsPanel()
  const [show, setShow] = useState<Show>('all')
  const [source, setSource] = useState<LogSource | undefined>()
  const [query, setQuery] = useState('')
  const [follow, setFollow] = useState(true)
  const [pausedAt, setPausedAt] = useState(0)
  const [clearedAt, setClearedAt] = useState(0)
  const [folds, setFolds] = useState<Set<number>>(() => new Set())
  const logs = useLiveLogs(useMemo(() => serverFilters(scope, show, source), [scope, show, source]))
  const { runs, now, projectName } = useLogRuns()

  // Version tags for the lines' context (the API sends ids)
  const seenKey = useMemo(() => [...new Set(logs.rows.map((r) => r.project).filter((p): p is string => !!p))]
    .slice(0, 12).join(','), [logs.rows])
  const tags = useVersionTags(useMemo(() => (seenKey ? seenKey.split(',') : []), [seenKey]))
  const tagsKey = JSON.stringify(tags)
  const versionTag = useMemo(() => {
    const t: Record<string, string> = JSON.parse(tagsKey)
    return (id: string) => t[id] ?? id
  }, [tagsKey])

  // A new scope or filter starts a new list: nothing cleared, the newest line in view.
  const restart = useCallback(() => { setClearedAt(0); setFollow(true) }, [])
  const shown = useMemo(() => logs.rows.filter((r) => r.seq > clearedAt && matches(r, query)), [logs.rows, clearedAt, query])
  const unseen = follow ? 0 : shown.filter((r) => r.seq > pausedAt).length
  const oneRun = isOneRun(scope)
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
  const toggleFold = useCallback((seq: number) => setFolds((s) => {
    const n = new Set(s)
    if (!n.delete(seq)) n.add(seq)
    return n
  }), [])
  const pick = useCallback((s: Parameters<typeof setScope>[0]) => { setScope(s); restart() }, [setScope, restart])

  // Follow: stay at the newest line; scrolling up pauses it, the pill resumes it
  const listRef = useRef<HTMLDivElement>(null)
  useLayoutEffect(() => {
    const el = listRef.current
    if (el && follow) el.scrollTop = el.scrollHeight
  }, [shown, follow, height, maximized])
  const pause = () => { setFollow(false); setPausedAt(shown.at(-1)?.seq ?? 0) }
  const onScroll = () => {
    const el = listRef.current
    if (!el) return
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24
    if (atBottom && !follow) setFollow(true)
    else if (!atBottom && follow) pause()
  }

  // Esc closes
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') close() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close])

  // Resize by the top edge
  const startResize = (e: React.MouseEvent) => {
    e.preventDefault()
    const y0 = e.clientY
    const h0 = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect().height
    const move = (ev: MouseEvent) => setHeight(Math.min(window.innerHeight - 160, Math.max(MIN_HEIGHT, h0 + (y0 - ev.clientY))))
    const up = () => { window.removeEventListener('mousemove', move); window.removeEventListener('mouseup', up) }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }

  return (
    <section
      aria-label="Logs"
      className={cn('relative flex flex-col flex-shrink-0 bg-surface-container-lowest border-t border-outline-variant shadow-[0_-8px_32px_rgba(0,0,0,.18)]',
        maximized && 'flex-1 min-h-0')}
      // eslint-disable-next-line no-restricted-syntax -- the height the reader dragged it to
      style={maximized ? undefined : { height }}
    >
      {!maximized && (
        <div onMouseDown={startResize} title="Drag to resize"
          className="absolute -top-1 inset-x-0 h-2 cursor-ns-resize after:content-[''] after:absolute after:left-1/2 after:top-[3px] after:w-10 after:h-[3px] after:-ml-5 after:rounded-full after:bg-outline-variant" />
      )}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3.5 py-2 border-b border-outline-variant">
        <span className="inline-flex items-center gap-2 text-sm font-semibold text-on-surface">
          <Icon name="terminal" size={18} />Logs
          <Status status={logs.status} retryIn={logs.retryIn} onReconnect={logs.reconnect} />
        </span>
        <ScopePicker scope={scope} onPick={pick} runs={runs} projectId={projectId} now={now} projectName={projectName} />
        <Segmented label="Show" value={show} onChange={(v) => { setShow(v); restart() }}
          options={[{ value: 'all', label: 'All' }, { value: 'warn', label: 'Warnings & errors' }, { value: 'debug', label: 'Debug' }]} />
        <Segmented label="Source" value={source ?? 'both'} onChange={(v) => { setSource(v === 'both' ? undefined : v as LogSource); restart() }}
          options={[{ value: 'both', label: 'All' }, { value: 'server', label: 'API' }, { value: 'engine', label: 'Engine' }]} />
        <label className="relative">
          <Icon name="search" size={16} className="absolute left-2 top-[7px] text-outline" />
          <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search the lines"
            aria-label="Search the lines"
            className="h-[30px] w-44 pl-7 pr-2 border border-outline-variant rounded-lg bg-surface-container-lowest text-xs text-on-surface placeholder:text-outline focus:outline-2 focus:outline-secondary" />
        </label>
        <span className="flex-1" />
        <button type="button" role="switch" aria-checked={follow} onClick={() => (follow ? pause() : setFollow(true))}
          title="Stay at the newest line" className="inline-flex items-center gap-1.5 text-xs text-on-surface-variant">
          <span className={cn('relative w-[26px] h-4 rounded-full transition-colors', follow ? 'bg-secondary' : 'bg-outline-variant')}>
            <span className={cn('absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white transition-transform', follow && 'translate-x-2.5')} />
          </span>
          Follow
        </button>
        <IconButton icon="clear_all" label="Clear (new lines keep arriving)" onClick={() => setClearedAt(logs.rows.at(-1)?.seq ?? 0)} />
        <IconButton icon={maximized ? 'close_fullscreen' : 'open_in_full'} label={maximized ? 'Back to its size' : 'Full height'} onClick={toggleMax} />
        <IconButton icon="close" label="Close (Esc)" onClick={close} />
      </div>

      <div ref={listRef} onScroll={onScroll} className="flex-1 min-h-0 overflow-y-auto">
        {logs.forbidden && <Note>Superusers only.</Note>}
        {logs.loading && <Note>Reading the logs…</Note>}
        {logs.error && !logs.loading && !logs.forbidden && <Note>Could not read the logs: {logs.error.message}</Note>}
        {!logs.loading && !logs.error && !shown.length && (
          <Note>{clearedAt && !query ? 'Cleared. New lines appear here as they arrive.' : 'No lines match. New ones appear here as they arrive.'}</Note>
        )}
        {shown.map((r) => (
          <Fragment key={r.seq}>
            {stepStarts.has(r.seq) && (
              <div className="flex items-center gap-2 px-3.5 pt-2 pb-0.5 font-mono text-label font-semibold uppercase tracking-[0.06em] text-secondary after:content-[''] after:flex-1 after:h-px after:bg-info-line">
                {r.step}
              </div>
            )}
            <LogRow r={r} oneRun={oneRun} everyProject={scope.kind === 'all'} query={query} open={folds.has(r.seq)}
              onToggle={toggleFold} onPick={pick} projectName={projectName} versionTag={versionTag} />
          </Fragment>
        ))}
      </div>
      {unseen > 0 && (
        <button type="button" onClick={() => setFollow(true)}
          className="absolute left-1/2 -translate-x-1/2 bottom-3.5 inline-flex items-center gap-1.5 h-7 px-3 rounded-full bg-secondary text-on-secondary text-xs font-semibold shadow-[0_8px_24px_rgba(0,0,0,.25)]">
          <Icon name="arrow_downward" size={15} />{unseen} new line{unseen === 1 ? '' : 's'}
        </button>
      )}
    </section>
  )
}

function Note({ children }: { children: ReactNode }) {
  return <p className="px-4 py-10 text-center text-body text-outline">{children}</p>
}

function IconButton({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} title={label} aria-label={label}
      className="inline-flex items-center justify-center w-[30px] h-[30px] rounded-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface">
      <Icon name={icon} size={18} />
    </button>
  )
}

function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: { value: T; label: string }[]; onChange: (v: T) => void; label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex h-[30px] border border-outline-variant rounded-lg overflow-hidden bg-surface-container-lowest">
      {options.map((o) => (
        <button key={o.value} type="button" role="radio" aria-checked={value === o.value} onClick={() => onChange(o.value)}
          className={cn('px-2.5 text-xs whitespace-nowrap border-r border-outline-variant last:border-r-0',
            value === o.value ? 'bg-tint text-secondary font-semibold' : 'text-on-surface-variant hover:text-on-surface')}>
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Status({ status, retryIn, onReconnect }: { status: LiveStatus; retryIn: number | null; onReconnect: () => void }) {
  const tone = status === 'live' ? 'text-success' : status === 'reconnecting' ? 'text-warn' : 'text-on-surface-variant'
  const dot = status === 'live' ? 'bg-success' : status === 'reconnecting' ? 'bg-warn' : 'bg-outline'
  const text = status === 'live' ? 'Live'
    : status === 'reconnecting' ? (retryIn ? `Reconnecting in ${retryIn} s` : 'Reconnecting')
      : status === 'stopped' ? 'Stopped' : 'Connecting'
  return (
    <span role="status" className={cn('inline-flex items-center gap-1.5 text-xs font-medium', tone)}>
      <span className={cn('w-[7px] h-[7px] rounded-full', dot)} aria-hidden />
      {text}
      {status === 'stopped' && (
        <button type="button" onClick={onReconnect} className="ml-1 text-secondary hover:underline">Reconnect</button>
      )}
    </span>
  )
}
