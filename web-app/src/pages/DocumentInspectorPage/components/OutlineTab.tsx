import { useEffect, useMemo, useRef, useState } from 'react'
import { Icon, Input, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { ancestorsOf, defaultExpanded, filterOutline, type OutlineNode } from '../outline'

/* The document's outline. A firmware document has hundreds of functions, so units start folded,
   a search narrows the tree to what matches, and the section you are reading is marked and its
   unit opened as you scroll. In edit mode each unit shows how many corrections it holds. */
export function OutlineTab({
  nodes, activeId, counts, onJump,
}: {
  nodes: OutlineNode[]
  activeId: string | null
  /** Corrections per unit key; null outside edit mode. */
  counts: Map<string, number> | null
  onJump: (id: string) => void
}) {
  const [query, setQuery] = useState('')
  const [userOpen, setUserOpen] = useState<Set<string>>(() => new Set())
  const [userClosed, setUserClosed] = useState<Set<string>>(() => new Set())
  const listRef = useRef<HTMLElement>(null)

  const defaults = useMemo(() => defaultExpanded(nodes), [nodes])
  const activePath = useMemo(() => new Set(activeId ? ancestorsOf(nodes, activeId) : []), [nodes, activeId])
  const { nodes: shown, hits } = useMemo(() => filterOutline(nodes, query), [nodes, query])
  const searching = query.trim().length > 0
  const units = useMemo(() => {
    let u = 0, f = 0
    const walk = (list: OutlineNode[]) => list.forEach((n) => {
      if (n.unitKey) { u += 1; f += n.children.length }
      walk(n.children)
    })
    walk(nodes)
    return { u, f }
  }, [nodes])

  const isOpen = (id: string) =>
    searching || ((defaults.has(id) || userOpen.has(id) || activePath.has(id)) && !userClosed.has(id))

  function toggle(id: string) {
    const open = isOpen(id)
    setUserOpen((s) => { const n = new Set(s); if (open) n.delete(id); else n.add(id); return n })
    setUserClosed((s) => { const n = new Set(s); if (open) n.add(id); else n.delete(id); return n })
  }

  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [activeId])

  const q = query.trim().toLowerCase()
  const renderNodes = (list: OutlineNode[]): React.ReactNode => list.map((n) => {
    const open = isOpen(n.id)
    const count = n.unitKey ? counts?.get(n.unitKey) ?? 0 : 0
    return (
      <div key={n.id}>
        <div className={cn('flex items-center', n.depth > 0 && 'pl-2.5')}>
          {n.children.length > 0 ? (
            <button
              type="button"
              onClick={() => toggle(n.id)}
              aria-label={`${open ? 'Fold' : 'Open'} ${n.title}`}
              aria-expanded={open}
              className="w-[18px] h-[18px] flex-shrink-0 flex items-center justify-center rounded text-outline hover:bg-surface-container hover:text-secondary"
            >
              <Icon name={open ? 'expand_more' : 'chevron_right'} size={16} />
            </button>
          ) : <span className="w-[18px] flex-shrink-0" />}
          <button
            type="button"
            data-active={n.id === activeId ? 'true' : undefined}
            aria-current={n.id === activeId ? 'location' : undefined}
            onClick={() => onJump(n.id)}
            className={cn(
              'flex-1 min-w-0 flex items-baseline gap-1.5 text-left px-1.5 py-1 rounded-lg text-body transition-colors',
              n.id === activeId ? 'bg-surface-container-low text-secondary font-semibold' : 'text-on-surface-variant hover:text-on-surface hover:bg-surface-container-low',
            )}
          >
            {n.number && <span className="font-mono text-label text-outline flex-shrink-0">{n.number}</span>}
            <span className="truncate">{highlight(n.title, q)}</span>
            {count > 0 && (
              <span className="ml-auto flex-shrink-0 font-mono text-label font-semibold text-secondary" title={`${count} correction${count === 1 ? '' : 's'} in this unit`}>
                ● {count}
              </span>
            )}
          </button>
        </div>
        {open && n.children.length > 0 && <div className="pl-2">{renderNodes(n.children)}</div>}
      </div>
    )
  })

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="px-3 pt-3 pb-2 flex-shrink-0">
        <Input
          leadingIcon="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Find a unit or function…"
          aria-label="Find a unit or function"
        />
        <Text as="p" variant="caption" className="font-mono mt-1.5">
          {searching ? `${hits} found`
            : `${units.u} unit${units.u === 1 ? '' : 's'} · ${units.f} function${units.f === 1 ? '' : 's'}${counts ? ' · ● corrections' : ''}`}
        </Text>
      </div>
      <nav ref={listRef} className="flex-1 overflow-y-auto pb-3 px-1.5">
        {shown.length ? renderNodes(shown) : (
          <Text as="p" variant="caption" className="px-2">Nothing matches “{query}”.</Text>
        )}
      </nav>
    </div>
  )
}

function highlight(text: string, q: string): React.ReactNode {
  if (!q) return text
  const i = text.toLowerCase().indexOf(q)
  if (i < 0) return text
  return <>{text.slice(0, i)}<mark className="bg-highlight text-inherit rounded-sm">{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>
}
