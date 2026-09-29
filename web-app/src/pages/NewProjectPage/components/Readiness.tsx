import { CodeText, Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'

/** One line of the Review step's checklist. `error` stops the project being created; `warn` is
 *  something it would miss (it can still be created); `ok` is done. */
export interface ReadinessItem {
  state: 'ok' | 'warn' | 'error'
  title: string
  detail?: string
  /** The step that fixes it. */
  fix?: number
}

const LOOK = {
  ok:    { icon: 'check_circle', cls: 'text-[#00a572]' },
  warn:  { icon: 'error',        cls: 'text-[#b45309]' },
  error: { icon: 'cancel',       cls: 'text-error' },
} as const

/** Step 5, first: is the project ready - what must be fixed, what it would miss - before the
 *  details of every step. */
export function Readiness({ items, onFix }: { items: ReadinessItem[]; onFix: (step: number) => void }) {
  const errors = items.filter((i) => i.state === 'error').length
  const warns = items.filter((i) => i.state === 'warn').length
  return (
    <div className={cn('rounded-xl border bg-white overflow-hidden', errors ? 'border-error' : 'border-outline-variant')}>
      <div className={cn('flex items-center gap-2.5 px-4 py-3 border-b border-outline-variant', errors ? 'bg-error-container' : 'bg-[#f0fff9]')}>
        <Icon name={errors ? 'block' : 'rocket_launch'} size={18} fill className={errors ? 'text-error' : 'text-[#00a572]'} />
        <div className="flex-1">
          <p className={cn('text-sm font-semibold', errors ? 'text-on-error-container' : 'text-on-surface')}>
            {errors ? `${errors === 1 ? 'One thing' : `${errors} things`} to fix before the project can be created` : 'Ready to create'}
          </p>
          {warns > 0 && (
            <p className="text-caption text-on-surface-variant mt-0.5">
              {warns === 1 ? 'One thing' : `${warns} things`} it would miss - fine to create now and fix later.
            </p>
          )}
        </div>
      </div>
      <ul className="divide-y divide-surface-container-low">
        {items.map((it, i) => (
          <li key={i} className="flex items-start gap-2.5 px-4 py-2.5">
            <Icon name={LOOK[it.state].icon} size={16} fill className={cn('flex-shrink-0 mt-px', LOOK[it.state].cls)} />
            <div className="flex-1 min-w-0">
              <p className="text-xs text-on-surface">{it.title}</p>
              {it.detail && <p className="text-caption text-on-surface-variant mt-0.5 break-words"><CodeText text={it.detail} /></p>}
            </div>
            {it.fix && it.state !== 'ok' && (
              <button type="button" onClick={() => onFix(it.fix as number)}
                className="flex-shrink-0 font-mono text-caption font-semibold text-secondary hover:underline">
                Fix in step {it.fix}
              </button>
            )}
          </li>
        ))}
      </ul>
    </div>
  )
}
