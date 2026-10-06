import { Icon } from '../ui'
import { cn } from '../../lib/cn'
import { STATUS_META } from '../../lib/reviewStatus'
import type { ComponentState, VersionComponent } from '../../types'

/* A component as a chip (the Components drawer): one word per state, the same everywhere. A chip
   an admin can pick is a button; picked, it is filled blue with a check. */

const CHIP: Record<ComponentState, { word: string; icon: string | null; tone: string; spin?: boolean }> = {
  generated: { word: 'Has documents', icon: 'check', tone: 'bg-state-done-bg border-state-done-line text-state-done' },
  stale: { word: 'Out of date', icon: 'history', tone: 'bg-state-warn-bg border-state-warn-line text-state-warn' },
  generating: { word: 'In progress', icon: 'autorenew', tone: 'bg-white border-state-busy-line text-secondary', spin: true },
  waiting: { word: 'Queued', icon: 'schedule', tone: 'bg-white border-hairline text-on-surface-variant' },
  stopped: { word: 'Stopped', icon: 'pause_circle', tone: 'bg-state-warn-bg border-state-warn-line text-state-warn' },
  failed: { word: 'Failed', icon: 'error', tone: 'bg-state-fail-bg border-state-fail-line text-error' },
  not_requested: { word: 'Not started', icon: null, tone: 'bg-white border-outline-variant text-on-surface-variant' },
}

/** The legend's order. */
const LEGEND: ComponentState[] = ['generated', 'stale', 'generating', 'waiting', 'stopped', 'failed', 'not_requested']

const BASE = 'inline-flex items-center gap-1 px-2 py-[3px] border rounded-[6px] font-mono text-caption whitespace-nowrap'

/** "Math: Has documents · SWE.3 Approved · SWE.4 In review"; a failed one adds its error. */
function tooltip(c: VersionComponent, canPick: boolean): string {
  const parts = [`${c.name}: ${CHIP[c.state].word}`]
  if (c.documents.length) {
    parts.push(c.documents.map((d) => `${d.process} ${STATUS_META[d.status]?.label ?? d.status}`).join(' · '))
  }
  if (c.state === 'failed' && c.error) parts.push(c.error)
  return parts.join(' · ') + (canPick ? ' — click to pick it' : '')
}

export function ComponentChip({ c, canPick, picked, onToggle }: {
  c: VersionComponent
  /** An admin, and the component has no documents yet. */
  canPick: boolean
  picked: boolean
  onToggle: () => void
}) {
  const s = CHIP[c.state]
  const title = tooltip(c, canPick)
  const icon = s.icon && <Icon name={s.icon} size={12} className={cn(s.spin && 'animate-spin')} />
  if (!canPick) {
    return <span className={cn(BASE, s.tone)} title={title}>{icon}{c.name}</span>
  }
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={picked}
      title={title}
      className={cn(BASE, s.tone, 'cursor-pointer hover:border-secondary',
        picked && 'bg-secondary border-secondary text-white hover:border-secondary')}
    >
      {picked ? <Icon name="check" size={12} /> : icon}
      {c.name}
    </button>
  )
}

/** What each chip says: its colours and icon, then the word. */
export function ChipLegend() {
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1 mt-2.5 text-caption text-outline" aria-label="What the chips say">
      {LEGEND.map((state) => {
        const s = CHIP[state]
        return (
          <li key={state} className="inline-flex items-center gap-1">
            <span className={cn('inline-flex items-center justify-center h-[14px] min-w-[18px] px-[5px] border rounded-[6px]', s.tone)} aria-hidden>
              {s.icon && <Icon name={s.icon} size={11} />}
            </span>
            {s.word}
          </li>
        )
      })}
    </ul>
  )
}
