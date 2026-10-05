import { useState, type ReactNode } from 'react'
import { Icon } from '../ui'
import { cn } from '../../lib/cn'
import { allKeys, groupKeys, layerKeys, compKey, scopeOf, tickState, toggleKeys, type TickState } from '../../lib/runScope'
import type { ArchLayer } from '../../types'

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

function Row({ state, name, count, icon, bold, disabled, open, onToggle, onTick }: {
  state: TickState
  name: string
  count?: string
  icon: string
  bold?: boolean
  disabled?: boolean
  /** Set for a node with children: whether they show. */
  open?: boolean
  onToggle?: () => void
  onTick: () => void
}) {
  return (
    <div onClick={disabled ? undefined : onTick}
      className={cn('flex items-center gap-1 min-h-7 pl-1 pr-2 rounded-lg', disabled ? 'opacity-50' : 'cursor-pointer hover:bg-surface-container-low')}>
      {onToggle ? (
        <button type="button" onClick={(e) => { e.stopPropagation(); onToggle() }}
          className="w-[18px] h-[18px] flex-shrink-0 flex items-center justify-center rounded-[2px] text-outline hover:bg-surface-container-high hover:text-secondary">
          <Icon name={open ? 'keyboard_arrow_down' : 'keyboard_arrow_right'} size={15} />
        </button>
      ) : <span className="w-[18px] flex-shrink-0" />}
      <input type="checkbox" tabIndex={-1} readOnly disabled={disabled} checked={state === 'all'}
        ref={(el) => { if (el) el.indeterminate = state === 'some' }}
        className="w-3.5 h-3.5 mx-0.5 flex-shrink-0 accent-secondary pointer-events-none" />
      <Icon name={icon} size={15} className={icon === 'deployed_code' ? 'text-on-surface-variant' : 'text-secondary'} />
      <span className={cn('flex-1 min-w-0 truncate font-mono text-xs text-on-surface', bold && 'font-bold')}>{name}</span>
      {count && <span className={cn('flex-shrink-0 font-mono text-label', state === 'some' ? 'text-secondary font-semibold' : 'text-outline')}>{count}</span>}
    </div>
  )
}

/** The Run modal's components (docs/ui-mockups/project-detail.html): a tree of checkboxes,
 *  layers open and groups closed to start, with a count, All / None, and a line saying what the
 *  version will hold. The ticks become the job's scope through `lib/runScope.scopeOf`. */
export function ScopeTree({ layers, ticked, onChange }: {
  layers: ArchLayer[]
  ticked: ReadonlySet<string>
  onChange: (next: Set<string>) => void
}) {
  const [openNodes, setOpenNodes] = useState<Record<string, boolean>>({})
  const isOpen = (key: string, byDefault: boolean) => openNodes[key] ?? byDefault
  const flip = (key: string, byDefault: boolean) => setOpenNodes((p) => ({ ...p, [key]: !(p[key] ?? byDefault) }))
  const tick = (keys: string[]) => onChange(toggleKeys(keys, ticked))

  const all = allKeys(layers)
  const total = all.length
  const n = all.filter((k) => ticked.has(k)).length
  const scope = scopeOf(layers, ticked)
  const ofTotal = (keys: string[]) => `${keys.filter((k) => ticked.has(k)).length} of `

  // What the version will hold: a narrower run makes a version with only those documents.
  let hint: ReactNode = total ? 'Tick at least one component to run.' : 'The project has no components.'
  if (scope?.type === 'project') {
    hint = <>All <b className="font-mono font-semibold text-on-surface-variant">{total}</b> components are analyzed; one document each.</>
  } else if (scope) {
    const one = scope.names.length === 1
    const shown = one ? scope.names[0].slice(scope.type === 'layer' ? 0 : scope.names[0].indexOf('.') + 1) : plural(scope.names.length, scope.type)
    hint = <>Only <b className="font-mono font-semibold text-on-surface-variant">{shown}</b> {one ? 'is' : 'are'} analyzed;
      this version holds {n === 1 ? 'its one document' : `${one ? 'its' : 'their'} ${n} documents`}.</>
  }

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      <div className="flex items-center gap-2 mb-2">
        <Icon name="account_tree" size={16} className="text-secondary" />
        <span className="text-on-surface text-xs font-semibold">Components</span>
        <span className={cn('px-1.5 rounded-[3px] font-mono text-label font-semibold',
          n === 0 ? 'bg-error-container text-error' : n < total ? 'bg-surface-container text-secondary' : 'bg-surface-container-low text-outline')}>
          {n} of {total}
        </span>
        <span className="flex-1" />
        <button type="button" disabled={n === total} onClick={() => onChange(new Set(all))}
          className="text-caption text-secondary hover:underline disabled:text-outline-variant disabled:no-underline">All</button>
        <span className="text-caption text-outline">·</span>
        <button type="button" disabled={n === 0} onClick={() => onChange(new Set())}
          className="text-caption text-secondary hover:underline disabled:text-outline-variant disabled:no-underline">None</button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain p-1 bg-white border border-outline-variant rounded-xl">
        <Row state={tickState(all, ticked)} name="All components" count={plural(total, 'component')} icon="select_all" onTick={() => tick(all)} disabled={!total} />
        {layers.map((l) => {
          const lKeys = layerKeys(l)
          const lState = tickState(lKeys, ticked)
          const lOpen = isOpen(l.name, true)
          return (
            <div key={l.name}>
              <Row state={lState} name={l.name} icon="layers" bold disabled={!lKeys.length}
                count={!lKeys.length ? 'no components' : lState === 'some' ? `${ofTotal(lKeys)}${plural(lKeys.length, 'component')}` : plural(l.groups.length, 'group')}
                open={lOpen} onToggle={l.groups.length ? () => flip(l.name, true) : undefined} onTick={() => tick(lKeys)} />
              {lOpen && l.groups.length > 0 && (
                <div className="ml-[13px] pl-1.5 border-l border-outline-variant">
                  {l.groups.map((g) => {
                    const gKeys = groupKeys(l, g)
                    const gState = tickState(gKeys, ticked)
                    const gId = JSON.stringify([l.name, g.name])
                    const gOpen = isOpen(gId, false)
                    return (
                      <div key={g.name}>
                        <Row state={gState} name={g.name} icon={gOpen ? 'folder_open' : 'folder'} disabled={!gKeys.length}
                          count={gState === 'some' ? `${ofTotal(gKeys)}${g.components.length}` : plural(g.components.length, 'component')}
                          open={gOpen} onToggle={gKeys.length ? () => flip(gId, false) : undefined} onTick={() => tick(gKeys)} />
                        {gOpen && (
                          <div className="ml-[13px] pl-1.5 border-l border-outline-variant">
                            {g.components.map((c) => {
                              const k = compKey(l.name, g.name, c.name)
                              return <Row key={c.name} state={ticked.has(k) ? 'all' : 'none'} name={c.name} icon="deployed_code" onTick={() => tick([k])} />
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}
      </div>

      <p className={cn('mt-2 text-caption', n === 0 && total ? 'text-error' : 'text-outline')}>{hint}</p>
    </div>
  )
}
