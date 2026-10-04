import type { RichSection, Slot } from '../../types'

/* The right panel's Outline and Corrections, as pure functions of the rendered document. A
   firmware document has hundreds of functions: the outline folds them under their unit, a
   search finds one, and the unit you are reading opens by itself. */

export interface OutlineNode {
  id: string
  number: string
  title: string
  /** 0 for a chapter; one more per nesting level shown. */
  depth: number
  children: OutlineNode[]
  /** A unit's key (`Comp|Unit`), for its corrections count. */
  unitKey?: string
}

/** The unit/interface tables of a unit are not listed: its functions are what a reader looks for. */
function listed(s: RichSection): boolean {
  if (!s.number) return false
  return !s.id.endsWith('-header') && !s.id.endsWith('-iface')
}

function unitKeyOf(s: RichSection): string | undefined {
  const iface = s.children.find((c) => c.id.endsWith('-iface'))
  return iface ? iface.id.slice(0, -'-iface'.length) : undefined
}

/** The document's numbered sections as a tree, down to `maxLevel`. */
export function buildOutline(sections: RichSection[], maxLevel = 4, depth = 0): OutlineNode[] {
  const out: OutlineNode[] = []
  for (const s of sections) {
    if (!listed(s) || s.level > maxLevel) {
      // An unnumbered section (a diagram, a table) may still hold numbered ones.
      if (!s.number) out.push(...buildOutline(s.children, maxLevel, depth))
      continue
    }
    const node: OutlineNode = {
      id: s.id, number: s.number, title: s.title, depth,
      children: buildOutline(s.children, maxLevel, depth + 1),
    }
    const uk = unitKeyOf(s)
    if (uk) node.unitKey = uk
    out.push(node)
  }
  return out
}

/** The nodes whose title matches `query` (case-insensitive), with their ancestors. */
export function filterOutline(nodes: OutlineNode[], query: string): { nodes: OutlineNode[]; hits: number } {
  const q = query.trim().toLowerCase()
  if (!q) return { nodes, hits: 0 }
  let hits = 0
  const walk = (list: OutlineNode[]): OutlineNode[] => {
    const kept: OutlineNode[] = []
    for (const n of list) {
      const children = walk(n.children)
      const self = n.title.toLowerCase().includes(q)
      if (self) hits += 1
      if (self || children.length) kept.push({ ...n, children: self && !children.length ? n.children : children })
    }
    return kept
  }
  return { nodes: walk(nodes), hits }
}

/** Every id, in document order. */
export function outlineIds(nodes: OutlineNode[]): string[] {
  return nodes.flatMap((n) => [n.id, ...outlineIds(n.children)])
}

/** The ids of `id`'s ancestors, outermost first; [] when it is not in the tree. */
export function ancestorsOf(nodes: OutlineNode[], id: string): string[] {
  for (const n of nodes) {
    if (n.id === id) return []
    const below = ancestorsOf(n.children, id)
    if (below.length || n.children.some((c) => c.id === id)) return [n.id, ...below]
  }
  return []
}

/** Open at first: chapters and their parts, unless a part lists a great many rows. */
export function defaultExpanded(nodes: OutlineNode[]): Set<string> {
  const open = new Set<string>()
  const walk = (list: OutlineNode[]) => {
    for (const n of list) {
      if (n.depth <= 1 && n.children.length && n.children.length <= 40) open.add(n.id)
      walk(n.children)
    }
  }
  walk(nodes)
  return open
}

/** Every slot the rendered document carries, walked once. */
export function docSlots(sections: RichSection[]): Slot[] {
  const out: Slot[] = []
  const add = (s: Slot | null | undefined) => { if (s) out.push(s) }
  const walk = (list: RichSection[]) => {
    for (const s of list) {
      s.table?.cellSlots?.forEach((row) => row.forEach(add))
      add(s.contentSlot)
      if (s.flowchartTable) {
        add(s.flowchartTable.descriptionSlot)
        add(s.flowchartTable.inputNameSlot)
        add(s.flowchartTable.outputNameSlot)
      }
      if (s.behaviorTable) {
        add(s.behaviorTable.descriptionSlot)
        add(s.behaviorTable.inputNameSlot)
        add(s.behaviorTable.outputNameSlot)
      }
      walk(s.children)
    }
  }
  walk(sections)
  return out
}

/** The flowchart ids the document draws. */
export function docFlowchartIds(sections: RichSection[]): Set<string> {
  const ids = new Set<string>()
  const walk = (list: RichSection[]) => {
    for (const s of list) {
      s.flowchartTable?.flowcharts.forEach((f) => { if (f.flowchartId) ids.add(f.flowchartId) })
      walk(s.children)
    }
  }
  walk(sections)
  return ids
}

/** The page prints a reviewer's words here: a correction in force that was not undone. An undone
 *  slot (R4) keeps its record — `isOverridden` stays true — but prints the LLM's text again and
 *  cannot be undone (API spec §5, "undone"), so it is not a correction to mark or count. */
export function isCorrected(s: Slot): boolean {
  return s.isOverridden && !s.isOrphaned && !(!s.canUndo && s.llmText !== null && s.text === s.llmText)
}

/** This document's corrections out of the version's (R1): the ones it prints, the undone ones
 *  (R4: the page prints the LLM's text again, but the Word file keeps the correction until a
 *  re-export, and R9 still counts it), and the orphans of its component. */
export function docCorrections(all: Slot[], sections: RichSection[], group: string): {
  inForce: Slot[]; undone: Slot[]; orphans: Slot[]
} {
  const keys = new Set(docSlots(sections).map((s) => s.key))
  const charts = docFlowchartIds(sections)
  const mine = (s: Slot) =>
    keys.has(s.key) || (s.kind === 'nodeLabel' && !!s.flowchartId && charts.has(s.flowchartId))
  return {
    inForce: all.filter((s) => isCorrected(s) && mine(s)),
    undone: all.filter((s) => s.isOverridden && !s.isOrphaned && !isCorrected(s) && mine(s)),
    orphans: all.filter((s) => s.isOrphaned && (mine(s) || s.key.startsWith(`${group}|`))),
  }
}

/** The undone corrections to list as "not in the Word file yet": every one of the document while
 *  its Word file is stale, none once it is not. Not cut off by time: a re-export can be partial
 *  (some components only), and R9's `oldestDerivationAt` is the version's, not the component's —
 *  so no time says which undo a given Word file already has. */
export function undoneInWordFile(undone: Slot[], wordFileStale: boolean): Slot[] {
  return wordFileStale ? undone : []
}

/** One slot of a version, by kind and key: a key alone may name two kinds (a function's
 *  description and its behaviour names share one). */
export const slotRef = (kind: string, key: string): string => `${kind}:${key}`

/** Corrections in force per unit key, for the outline's counts. */
export function unitCorrectionCounts(inForce: Slot[], sections: RichSection[]): Map<string, number> {
  // A struct's key is its type name, not under the unit: find its unit by its header row.
  const structUnit = new Map<string, string>()
  const walk = (list: RichSection[]) => {
    for (const s of list) {
      if (s.id.endsWith('-header')) {
        const uk = s.id.slice(0, -'-header'.length)
        s.table?.cellSlots?.forEach((row) => row.forEach((c) => { if (c) structUnit.set(c.key, uk) }))
      }
      walk(s.children)
    }
  }
  walk(sections)
  const counts = new Map<string, number>()
  for (const s of inForce) {
    const uk = s.kind === 'structDescription'
      ? structUnit.get(s.key)
      : s.key.split('\u0001')[0].split('|').slice(0, 2).join('|')
    if (uk) counts.set(uk, (counts.get(uk) ?? 0) + 1)
  }
  return counts
}

/** Where a correction is, in words: the function, unit or type its key names. */
export function slotWhere(s: Slot): string {
  const head = s.key.split('\u0001')[0]
  const parts = head.split('|')
  if (s.kind === 'structDescription') return head
  if (s.kind === 'unitDescription') return `unit ${parts[1] ?? head}`
  const name = parts[2] ?? head
  if (s.kind === 'nodeLabel') return `${name} · box ${s.nodeId ?? ''}`.trim()
  return name
}

/** A flowchart's boxes in the order its arrows run, from the DOT (`N1 -> N3;`): breadth first
 *  from the boxes nothing points to. Ids the DOT does not order go last. */
export function flowOrder(dot: string): Map<string, number> {
  const next = new Map<string, string[]>()
  const nodes: string[] = []
  const seen = new Set<string>()
  const add = (id: string) => { if (!seen.has(id)) { seen.add(id); nodes.push(id) } }
  const into = new Set<string>()
  for (const m of dot.matchAll(/^\s*"?([\w.]+)"?\s*\[/gm)) add(m[1])
  for (const m of dot.matchAll(/"?([\w.]+)"?\s*->\s*"?([\w.]+)"?/g)) {
    add(m[1]); add(m[2])
    next.set(m[1], [...(next.get(m[1]) ?? []), m[2]])
    into.add(m[2])
  }
  const order = new Map<string, number>()
  const queue = nodes.filter((n) => !into.has(n))
  while (queue.length) {
    const n = queue.shift() as string
    if (order.has(n)) continue
    order.set(n, order.size)
    queue.push(...(next.get(n) ?? []))
  }
  for (const n of nodes) if (!order.has(n)) order.set(n, order.size)
  return order
}

export const SLOT_KIND_LABEL: Record<string, string> = {
  description: 'Description',
  behaviourInputName: 'Input name',
  behaviourOutputName: 'Output name',
  behaviourDescription: 'Behaviour',
  unitDescription: 'Unit description',
  structDescription: 'Struct description',
  nodeLabel: 'Flowchart label',
}
