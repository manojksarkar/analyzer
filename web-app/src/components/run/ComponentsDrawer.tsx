import { useState } from 'react'
import { useGenerateComponents } from '../../hooks/useVersionComponents'
import { Button, Drawer, Icon } from '../ui'
import { cn } from '../../lib/cn'
import {
  componentTree, filterTree, hasDocuments, layerNote, layersAdded, pickable,
} from '../../lib/versionComponents'
import type { ArchLayer, VersionComponent, VersionComponents } from '../../types'
import { ChipLegend, ComponentChip } from './ComponentChip'

/* Every component of the version, laid out like the Architecture view (layer → group → chips), so
   3 layers and 50+ components fit on one screen. A chip says what is happening to the component;
   an admin picks the ones without documents (a click, or a layer's at once with "Select N") and
   generates them into this same version (Phases 3–4 from its stored model; `analyzer.py export`
   on the server). One of a layer the model lacks can be picked too: the job adds that layer first
   (parse + descriptions). A developer reads it. */

const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? '' : 's'}`

function Bar({ share, className }: { share: number; className: string }) {
  return (
    <span className="block w-14 h-1 rounded-full bg-track overflow-hidden flex-shrink-0" aria-hidden>
      {/* eslint-disable-next-line no-restricted-syntax -- the share done is data-driven */}
      <span className={cn('block h-full', className)} style={{ width: `${Math.round(100 * share)}%` }} />
    </span>
  )
}

export function ComponentsDrawer({ projectId, versionId, versionTag, data, isAdmin, layers, onClose, onStarted }: {
  projectId: string
  versionId: string
  versionTag?: string
  data: VersionComponents
  isAdmin: boolean
  /** The project's architecture: the group of a component the API names none for, and the order. */
  layers?: ArchLayer[]
  onClose: () => void
  /** A Generate started: the banner reads again until its job shows. */
  onStarted: () => void
}) {
  const generate = useGenerateComponents(projectId, versionId)
  const [query, setQuery] = useState('')
  const [withoutOnly, setWithoutOnly] = useState(false)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [folded, setFolded] = useState<Set<string>>(new Set())

  const comps = data.components
  const total = comps.length
  const withDocs = comps.filter(hasDocuments).length
  const tree = componentTree(comps, layers)
  const shown = filterTree(tree, query, withoutOnly)
  // Only what can still be asked for: a component made meanwhile drops out of the pick.
  const pickedNow = comps.filter((c) => isAdmin && pickable(c) && picked.has(c.id))
  const adding = layersAdded(pickedNow)
  // One writer per version: while a run (or a web job) is at work on it, nothing more starts —
  // the server would refuse it. Picking stays possible; Generate waits.
  const busy = data.run?.alive || data.job ? 'Generate after the run at work on this version ends.' : ''

  const toggle = (set: Set<string>, id: string) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  }
  function start() {
    generate.mutate(pickedNow.map((c) => c.id), {
      onSuccess: () => { setPicked(new Set()); onStarted() },
    })
  }

  const header = (
    <>
      <div className="flex items-center gap-2.5 mt-3">
        <label className="flex-1 min-w-0 flex items-center gap-1.5 px-2.5 py-1.5 border border-outline-variant rounded-[6px] focus-within:border-secondary">
          <Icon name="search" size={16} className="text-outline" />
          <input
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Find a component…"
            aria-label="Find a component"
            data-autofocus
            className="flex-1 min-w-0 bg-transparent outline-none text-xs text-on-surface placeholder:text-outline"
          />
        </label>
        <div role="group" aria-label="Show" className="flex gap-0.5 p-0.5 rounded-xl bg-surface-container-low flex-shrink-0">
          {([[false, `All ${total}`], [true, `Without documents ${total - withDocs}`]] as const).map(([only, label]) => (
            <button
              key={label}
              type="button"
              aria-pressed={withoutOnly === only}
              onClick={() => setWithoutOnly(only)}
              className={cn(
                'px-2.5 py-[5px] rounded-[6px] text-xs font-medium text-on-surface-variant whitespace-nowrap',
                withoutOnly === only && 'bg-surface-container-lowest text-on-surface shadow-[0_1px_2px_rgba(4,22,39,.12)]',
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      <ChipLegend />
    </>
  )

  const footer = isAdmin && (
    <>
      <div className="flex items-center gap-3">
        <p className="flex-1 min-w-0 text-xs text-outline">
          {pickedNow.length ? `${pickedNow.length} selected` : "Click the components to generate, or Select a layer's."}
        </p>
        {pickedNow.length > 0 && (
          <button type="button" onClick={() => setPicked(new Set())} className="text-xs font-medium text-secondary hover:underline">
            Clear
          </button>
        )}
        {/* The tooltip sits on a wrapper: a disabled button gets no pointer events. */}
        <span title={busy || undefined}>
          <Button size="sm" loading={generate.isPending} disabled={!pickedNow.length || !!busy} onClick={start}
            className="h-auto py-2 px-4 rounded-[6px] whitespace-nowrap">
            Generate{pickedNow.length ? ` ${pickedNow.length}` : ''}
          </Button>
        </span>
      </div>
      {busy ? (
        <p className="mt-1.5 text-right text-xs text-outline">{busy}</p>
      ) : pickedNow.length > 0 && (
        <p className="mt-1.5 text-right text-xs text-outline">
          {adding.length
            ? `Adds ${adding.join(', ')} first (parse + descriptions), then writes the documents`
            : 'Uses the analysis already done'}
        </p>
      )}
    </>
  )

  return (
    <Drawer
      open
      onClose={onClose}
      title="Components"
      description={
        <>
          {versionTag && <><span className="font-mono">{versionTag}</span> · </>}
          {withDocs} of {total} have documents · {plural(tree.length, 'layer')}
        </>
      }
      header={header}
      footer={footer || undefined}
    >
      <div className="pb-2">
        {shown.map((l) => {
          const all = l.all
          const done = all.filter(hasDocuments).length
          const visible = l.groups.flatMap((g) => g.comps)
          const selectable = isAdmin ? visible.filter((c) => pickable(c) && !picked.has(c.id)) : []
          const note = layerNote(l.layer, comps)
          const isFolded = folded.has(l.layer)
          const name = l.layer || 'No layer'
          return (
            <section key={l.layer || '—'} aria-label={name} className="px-6 py-3.5 border-t border-muted first:border-t-0">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setFolded((f) => toggle(f, l.layer))}
                  aria-expanded={!isFolded}
                  className="flex items-center gap-2 min-w-0"
                >
                  <Icon name="expand_more" size={16} className={cn('text-on-surface-variant transition-transform', isFolded && '-rotate-90')} />
                  <Icon name="layers" size={15} className="text-secondary" />
                  <span className="font-mono text-xs font-bold text-on-surface truncate">{name}</span>
                </button>
                <span className="text-xs text-outline whitespace-nowrap">{done} of {all.length}</span>
                <Bar share={all.length ? done / all.length : 0} className="bg-success" />
                <span className="flex-1" />
                {selectable.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setPicked((p) => new Set([...p, ...selectable.map((c) => c.id)]))}
                    className="text-xs font-medium text-secondary hover:underline whitespace-nowrap"
                  >
                    Select {selectable.length}
                  </button>
                )}
              </div>
              {!isFolded && (
                <div>
                  {note && (
                    <p className="flex items-start gap-1.5 mt-2 ml-6 text-xs text-on-surface-variant">
                      <Icon name="add_circle" size={14} className="text-secondary flex-shrink-0 mt-px" />
                      {note}
                    </p>
                  )}
                  {l.groups.map((g) => (
                    <div key={g.name ?? '—'} className="mt-2.5 ml-6">
                      {g.name !== null && (
                        <div className="flex items-center gap-1.5 mb-1.5">
                          <Icon name="folder_open" size={13} className="text-secondary" />
                          <span className="font-mono text-caption font-semibold text-on-surface">{g.name}</span>
                          <span className="font-mono text-label text-outline">{plural(g.size, 'comp')}</span>
                        </div>
                      )}
                      <div className={cn('flex flex-wrap gap-1.5', g.name !== null && 'ml-[19px]')}>
                        {g.comps.map((c: VersionComponent) => (
                          <ComponentChip
                            key={c.id}
                            c={c}
                            canPick={isAdmin && pickable(c)}
                            picked={picked.has(c.id)}
                            onToggle={() => setPicked((p) => toggle(p, c.id))}
                          />
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )
        })}
        {shown.length === 0 && <p className="p-6 text-xs text-outline">No component matches.</p>}
      </div>
    </Drawer>
  )
}
