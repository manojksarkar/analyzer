import type { ReactNode } from 'react'
import { useNavigate } from 'react-router-dom'
import { Icon } from '../../../components/ui'
import { ComponentChip } from '../../../components/run/ComponentChip'
import { useVersions } from '../../../hooks/useProjects'
import { useRunFacts, useVersionComponents } from '../../../hooks/useVersionComponents'
import { useRecentLogLines } from '../../../hooks/useLiveLogs'
import { cn } from '../../../lib/cn'
import { relativeTime } from '../../../lib/format'
import { runActivity } from '../../../lib/versionComponents'
import { useAuthStore } from '../../../store/auth'
import { runScope, useLogsPanel } from '../../../store/logsPanel'
import type { AnalysisJob, VersionComponent } from '../../../types'

/* Under the running card, while a run is at work: what it makes, what it was asked for, and what
   the code holds so far -- so a first run's page is not just four phase dots. Three cards, and for
   a superuser the run's newest log lines. Read from what the app already has: the version's
   components (the Components drawer's list), the job and the version, and GET .../run-facts. */

const MODE: Record<string, string> = { export: 'Export', reexport: 'Word file update', resume: 'Resume' }
const DOC_TYPES: Record<string, string> = { all: 'SWE.3 and SWE.4', swe3: 'SWE.3', swe4: 'SWE.4' }
/** The documents card lists this many components, the busiest first; the rest are counted. */
const LIST = 8
const ORDER: Record<string, number> = { generating: 0, failed: 1, stopped: 2, generated: 3, stale: 4, waiting: 5 }

export function RunCards({ projectId, job }: { projectId: string; job: AnalysisJob }) {
  const vid = job.versionId
  const isSuperuser = useAuthStore((s) => !!s.user?.isSuperuser)
  const { data: comps } = useVersionComponents(projectId, vid ?? undefined)
  const { data: facts } = useRunFacts(projectId, vid, true)
  const { data: versions } = useVersions(projectId)
  const recent = useRecentLogLines(projectId, vid, isSuperuser)
  const openLogs = useLogsPanel((s) => s.openLogs)
  const navigate = useNavigate()
  if (!vid) return null

  const version = versions?.find((v) => v.id === vid)
  const asked = (comps?.components ?? []).filter((c) => c.state !== 'not_requested')
  const inModel = (comps?.components ?? []).filter((c) => c.inModel).length
  const ready = asked.filter((c) => c.state === 'generated' || c.state === 'stale').length
  const shown = [...asked].sort((a, b) => (ORDER[a.state] ?? 9) - (ORDER[b.state] ?? 9)).slice(0, LIST)
  const scope = version?.run?.scope
  const scopeText = !scope || scope.type === 'project' || !scope.names.length
    ? 'The whole project'
    : `${scope.type === 'component' ? 'Components' : scope.type === 'layer' ? 'Layers' : 'Groups'}: ${scope.names.join(', ')}`
  const llm = facts?.llm
  const llmTrouble = !!llm && (llm.retries > 0 || llm.failedCalls > 0)
  const activity = runActivity(comps?.run)

  return (
    <div className="mb-7 -mt-4">
      {/* Superusers: the run's newest lines, one click from all of them */}
      {isSuperuser && (recent.data?.records.length ?? 0) > 0 && (
        <div className="mb-4 rounded-xl border border-outline-variant bg-surface-container-lowest px-4 py-2.5">
          <div className="flex items-center justify-between mb-1">
            <span className="font-mono text-label font-semibold uppercase tracking-[0.06em] text-outline">Latest lines</span>
            <button type="button" onClick={() => openLogs(runScope(projectId, vid, job.id, job.versionTag ?? undefined))}
              className="inline-flex items-center gap-1 text-xs font-semibold text-secondary hover:underline">
              <Icon name="terminal" size={14} />Open logs
            </button>
          </div>
          {recent.data!.records.map((r) => (
            <p key={r.seq} className="flex gap-3 font-mono text-xs leading-5 text-on-surface truncate [font-variant-ligatures:none]">
              <span className="text-outline flex-shrink-0">{r.ts.slice(11, 19)}</span>
              <span className={cn('truncate', r.level === 'WARNING' && 'text-warn', (r.level === 'ERROR' || r.level === 'CRITICAL') && 'text-error')}>
                {r.message.split('\n')[0]}
              </span>
            </p>
          ))}
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        {/* 1. The documents, as they are made: a component opens the moment it has them */}
        <Card title="Documents" note={asked.length ? `${ready} of ${asked.length} ready` : undefined}>
          {!comps && <Muted>Reading the components…</Muted>}
          {comps && !asked.length && <Muted>The components appear here once the model has them.</Muted>}
          <ul className="space-y-1.5">
            {shown.map((c) => <DocRow key={c.id} c={c} onOpen={(docId) => navigate(`/projects/${projectId}/documents/${docId}`)} />)}
          </ul>
          {asked.length > LIST && <Muted>+{asked.length - LIST} more</Muted>}
        </Card>

        {/* 2. What this run was asked for */}
        <Card title="This run">
          <Facts rows={[
            ['Version', job.versionTag ?? '—'],
            ['Commit', `${job.shortSha} on ${job.branch}`],
            ['Kind', MODE[job.mode] ?? 'Generate'],
            ['Asked for', asked.length && inModel ? `${scopeText} · ${asked.length} of ${inModel} components` : scopeText],
            ['Documents', DOC_TYPES[version?.run?.docType ?? 'all'] ?? 'SWE.3 and SWE.4'],
            ['Started', job.startedAt ? relativeTime(job.startedAt) : '—'],
          ]} />
        </Card>

        {/* 3. What the code holds so far, and how the LLM is doing */}
        <Card title="Found so far">
          <Facts rows={[
            ['Code', facts?.model
              ? `${n(facts.model.functions)} functions · ${n(facts.model.globals)} globals · ${n(facts.model.units)} units · ${n(facts.model.components)} components`
              : 'Counted once the parse is stored'],
            ['Parse', facts ? (facts.parseWarnings ? <span className="text-warn">{facts.parseWarnings} warning{facts.parseWarnings === 1 ? '' : 's'}</span> : 'No warnings') : '—'],
            ['Now', activity || job.currentActivity || '—'],
            ['LLM', !llm ? '—' : llmTrouble
              ? <span className="text-warn" title={llm.lastFailure?.message}>
                  {llm.failedCalls ? `${llm.failedCalls} call${llm.failedCalls === 1 ? '' : 's'} failed` : ''}
                  {llm.failedCalls && llm.retries ? ' · ' : ''}
                  {llm.retries ? `${llm.retries} retr${llm.retries === 1 ? 'y' : 'ies'}` : ''}
                </span>
              : <span className="text-success">Answering</span>],
          ]} />
          {llmTrouble && llm?.lastFailure && (
            <p className="mt-2 font-mono text-label leading-4 text-warn break-words line-clamp-2" title={llm.lastFailure.message}>
              {llm.lastFailure.message}
            </p>
          )}
        </Card>
      </div>
    </div>
  )
}

const n = (x: number) => x.toLocaleString()

function Card({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section aria-label={title} className="rounded-xl border border-outline-variant bg-surface-container-lowest px-4 py-3.5 min-w-0">
      <div className="flex items-baseline justify-between mb-2.5">
        <h3 className="text-body font-semibold text-on-surface">{title}</h3>
        {note && <span className="font-mono text-caption text-on-surface-variant">{note}</span>}
      </div>
      {children}
    </section>
  )
}

function Facts({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[88px_minmax(0,1fr)] gap-x-3 gap-y-1.5 text-xs">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-on-surface-variant">{k}</dt>
          <dd className="text-on-surface min-w-0 break-words">{v}</dd>
        </div>
      ))}
    </dl>
  )
}

function Muted({ children }: { children: ReactNode }) {
  return <p className="text-xs text-on-surface-variant mt-1">{children}</p>
}

function DocRow({ c, onOpen }: { c: VersionComponent; onOpen: (docId: string) => void }) {
  return (
    <li className="flex items-center justify-between gap-2 min-w-0">
      <ComponentChip c={c} canPick={false} picked={false} onToggle={() => {}} />
      <span className="flex items-center gap-2 flex-shrink-0">
        {c.documents.map((d) => (
          <button key={d.id} type="button" onClick={() => onOpen(d.id)}
            className="font-mono text-caption font-semibold text-secondary hover:underline">{d.process}</button>
        ))}
      </span>
    </li>
  )
}
