import { useState } from 'react'
import { useGenerateComponents, useVersionComponents } from '../../../hooks/useVersionComponents'
import { useCancelJob } from '../../../hooks/useJobs'
import { Badge, Button, Card, Icon, Text } from '../../../components/ui'
import type { BadgeVariant } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { relativeTime } from '../../../lib/format'
import { STATUS_META } from '../../../lib/reviewStatus'
import type { ComponentState, VersionComponent, VersionJob, VersionRun } from '../../../types'
import { componentsByLayer, pickable } from '../helpers'
import { StopRunDialog } from '../../../components/run/StopRunDialog'

/* Staged generation: every component of the layers the version parsed and the state of its
   documents — generated, being made, waiting, stopped, failed, or not generated yet — with the
   version's latest run. An admin ticks components that have no documents and generates them into
   this same version (Phases 3–4 from its stored model; `analyzer.py export` on the server). */

const STATE: Record<ComponentState, { label: string; variant: BadgeVariant; icon: string }> = {
  generated: { label: 'Generated', variant: 'success', icon: 'check_circle' },
  generating: { label: 'Generating', variant: 'primary', icon: 'autorenew' },
  waiting: { label: 'Waiting', variant: 'default', icon: 'schedule' },
  stopped: { label: 'Stopped', variant: 'warning', icon: 'pause_circle' },
  failed: { label: 'Failed', variant: 'danger', icon: 'error' },
  not_requested: { label: 'Not generated', variant: 'mono', icon: 'radio_button_unchecked' },
}
const ORDER: ComponentState[] = ['generated', 'generating', 'waiting', 'stopped', 'failed', 'not_requested']

function RunStrip({ run, job, cutShort, projectId, versionId, onStop }: {
  run: VersionRun | null; job: VersionJob | null; cutShort: number; projectId: string; versionId: string
  /** An admin's Stop, when a web job is at work on the version. */
  onStop?: () => void
}) {
  if (run?.alive || job) {
    const live = run?.alive ? run : null
    const pct = live?.total ? Math.floor((100 * (live.done ?? 0)) / live.total) : null
    return (
      <div className="flex items-center gap-2 px-5 py-2.5 border-b border-outline-variant bg-surface">
        <Icon name="autorenew" size={15} className="text-secondary animate-spin flex-shrink-0" />
        <Text as="p" variant="caption" className="font-mono flex-1 min-w-0">
          {live ? (live.command === 'web run' ? 'Generating' : `Running ${live.command}`) : 'Starting the run…'}
          {live?.stage ? ` — ${live.stage.replace(/-/g, ' ')}` : ''}
          {live?.total ? ` ${live.done ?? 0}/${live.total}${pct !== null ? ` (${pct}%)` : ''}` : ''}
          {live?.startedAt ? ` · started ${relativeTime(live.startedAt)}` : ''}
        </Text>
        {job && onStop && (
          <Button variant="outline" size="sm" onClick={onStop} className="flex-shrink-0 text-[#991b1b]">
            <Icon name="stop_circle" size={14} />
            Stop
          </Button>
        )}
      </div>
    )
  }
  if (run?.stopped || cutShort > 0) {
    return (
      <div className="flex items-start gap-2 px-5 py-2.5 border-b border-[#fcd34d] bg-[#fffbeb]">
        <Icon name="warning" size={15} className="text-[#b45309] flex-shrink-0 mt-px" />
        <div className="min-w-0">
          <p className="font-mono text-caption text-[#92400e]">
            {run?.stopped
              ? `Its ${run.command} stopped ${relativeTime(run.progressAt ?? run.startedAt)} before it finished. Continue it on the server:`
              : `${cutShort} component${cutShort === 1 ? ' was' : 's were'} cut short or failed. Make them again on the server:`}
          </p>
          <code className="block mt-1 font-mono text-label text-[#92400e] bg-[#fef3c7] px-1.5 py-0.5 rounded-[3px] break-all select-all">
            python analyzer.py resume --project-id {projectId} --version-id {versionId} --detach
          </code>
        </div>
      </div>
    )
  }
  return null
}

function ComponentRow({ c, canPick, picked, onToggle }: {
  c: VersionComponent; canPick: boolean; picked: boolean; onToggle: () => void
}) {
  const s = STATE[c.state]
  return (
    <li className="flex items-center gap-2.5 px-3 py-2 rounded-lg border border-outline-variant bg-white min-w-0">
      {canPick ? (
        <input
          type="checkbox"
          aria-label={`Generate ${c.name}`}
          checked={picked}
          onChange={onToggle}
          className="accent-secondary w-[15px] h-[15px] cursor-pointer flex-shrink-0"
        />
      ) : (
        <span className="w-[15px] flex-shrink-0" aria-hidden />
      )}
      <span className="flex-1 min-w-0">
        <span className="block font-mono text-body text-on-surface truncate">{c.name}</span>
        {c.documents.length > 0 && (() => {
          const docs = c.documents.map((d) => `${d.process} ${STATUS_META[d.status]?.label ?? d.status}`).join(' · ')
          return <span className="block font-mono text-label text-outline truncate mt-px" title={docs}>{docs}</span>
        })()}
        {c.state === 'failed' && c.error && (
          <span className="block font-mono text-label text-[#991b1b] truncate mt-px" title={c.error}>{c.error}</span>
        )}
      </span>
      <Badge variant={s.variant} className="flex-shrink-0 gap-1 font-mono text-label">
        <Icon name={s.icon} size={12} className={cn(c.state === 'generating' && 'animate-spin')} />
        {s.label}
      </Badge>
    </li>
  )
}

export function ComponentsPanel({ projectId, versionId, isAdmin }: {
  projectId: string
  versionId: string
  isAdmin: boolean
}) {
  const [pollUntil, setPollUntil] = useState(0)
  const { data } = useVersionComponents(projectId, versionId, pollUntil)
  const generate = useGenerateComponents(projectId, versionId)
  const cancel = useCancelJob(projectId)
  const [stopping, setStopping] = useState(false)
  const [open, setOpen] = useState<boolean | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())

  if (!data || data.components.length === 0) return null
  const comps = data.components
  const generated = data.counts.generated ?? 0
  const allDone = generated === comps.length && !data.run?.alive
  // Collapsed once everything is generated; open while something is missing or being made.
  const expanded = open ?? !allDone
  const choosable = comps.filter(pickable)
  const pickedNow = choosable.filter((c) => picked.has(c.id))
  const bar = { width: `${Math.round((100 * generated) / comps.length)}%` }

  function toggle(id: string) {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  function start() {
    generate.mutate(pickedNow.map((c) => c.id), {
      onSuccess: () => { setPicked(new Set()); setPollUntil(Date.now() + 120_000) },
    })
  }
  function stop(job: VersionJob) {
    cancel.mutate(job.id, {
      // The run takes a few seconds to stop: keep reading until it has.
      onSuccess: () => { setStopping(false); setPollUntil(Date.now() + 60_000) },
    })
  }

  return (
    <Card className="overflow-hidden mb-4">
      <button
        type="button"
        onClick={() => setOpen(!expanded)}
        aria-expanded={expanded}
        className="w-full flex items-center gap-3 px-5 py-3.5 text-left hover:bg-surface transition-colors"
      >
        <Icon name="widgets" size={18} className="text-on-surface-variant flex-shrink-0" />
        <span className="flex-1 min-w-0">
          <Text as="span" variant="title" className="text-on-surface">Components</Text>
          <Text as="span" variant="caption" className="font-mono ml-2">
            {generated} of {comps.length} generated
            {ORDER.filter((s) => s !== 'generated' && data.counts[s]).map((s) => ` · ${data.counts[s]} ${STATE[s].label.toLowerCase()}`).join('')}
          </Text>
          <span className="block mt-2 h-1 rounded-full bg-surface-container overflow-hidden" aria-hidden>
            {/* eslint-disable-next-line no-restricted-syntax -- the share generated is data-driven */}
            <span className="block h-full bg-[#00a572]" style={bar} />
          </span>
        </span>
        <Icon name="expand_more" size={18} className={cn('text-on-surface-variant transition-transform', expanded && 'rotate-180')} />
      </button>

      <RunStrip
        run={data.run}
        job={data.job}
        cutShort={comps.filter((c) => c.inModel && (c.state === 'stopped' || c.state === 'failed')).length}
        projectId={projectId}
        versionId={versionId}
        onStop={isAdmin ? () => setStopping(true) : undefined}
      />
      {stopping && data.job && (
        <StopRunDialog
          job={data.job}
          busy={cancel.isPending}
          onConfirm={() => data.job && stop(data.job)}
          onClose={() => setStopping(false)}
        />
      )}

      {expanded && (
        <div className="px-5 py-4 border-t border-outline-variant space-y-4 bg-surface-container-low">
          {componentsByLayer(comps).map(([layer, list]) => {
            const done = list.filter((c) => c.state === 'generated').length
            return (
              <section key={layer || '—'}>
                <Text as="h3" variant="label" className="mb-2">
                  {layer || 'No layer'} · {done} of {list.length} generated
                </Text>
                <ul className="grid gap-2 grid-cols-[repeat(auto-fill,minmax(260px,1fr))]">
                  {list.map((c) => (
                    <ComponentRow
                      key={c.id}
                      c={c}
                      canPick={isAdmin && pickable(c)}
                      picked={picked.has(c.id)}
                      onToggle={() => toggle(c.id)}
                    />
                  ))}
                </ul>
              </section>
            )
          })}

          {isAdmin && choosable.length > 0 && (
            <div className="flex items-center justify-between gap-3 pt-1">
              <button
                type="button"
                onClick={() => setPicked(pickedNow.length === choosable.length ? new Set() : new Set(choosable.map((c) => c.id)))}
                className="font-mono text-caption text-secondary hover:underline"
              >
                {pickedNow.length === choosable.length ? 'Clear' : `Select all not generated (${choosable.length})`}
              </button>
              <div className="flex items-center gap-3">
                <Text as="span" variant="caption" className="font-mono hidden sm:inline">
                  From this version's model: no parsing, no new descriptions.
                </Text>
                <Button size="sm" loading={generate.isPending} disabled={!pickedNow.length} onClick={start}>
                  <Icon name="play_arrow" size={14} />
                  Generate {pickedNow.length || ''}
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}
