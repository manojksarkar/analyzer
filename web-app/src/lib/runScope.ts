import type { JobScope } from '../services/api'
import type { ArchGroup, ArchLayer } from '../types'

/**
 * The Run modal's component tree (docs/ui-mockups/project-detail.html). Every component starts
 * ticked; the user unticks to narrow the run. A run makes one document per component whatever
 * its scope (`--component-per-docx`), so the ticks only say WHICH components are analyzed.
 *
 * The engine's `--scope` names several things of ONE kind - `layer:A,B`, `group:A,B` or
 * `component:A,B` (analyzer.py `_parse_scope`) - and they may sit in different layers. A ticked
 * layer or group is all of its components, so any mix of ticks can be sent: `scopeOf` picks the
 * smallest form that says exactly those ticks.
 */

/** A component in the tree: its layer, group and name (names may hold any character). */
export const compKey = (layer: string, group: string, comp: string) => JSON.stringify([layer, group, comp])

export const groupKeys = (l: ArchLayer, g: ArchGroup) => g.components.map((c) => compKey(l.name, g.name, c.name))
export const layerKeys = (l: ArchLayer) => l.groups.flatMap((g) => groupKeys(l, g))
export const allKeys = (layers: ArchLayer[]) => layers.flatMap(layerKeys)

/** The tree's keys of the components a version has documents for (its components answer: `id` is
 *  `Layer.Component`). An incremental run is compared against such a version: it starts from what
 *  that version made, not from every component -- a whole project's run takes hours. */
export function keysWithDocuments(layers: ArchLayer[], comps: { id: string; documents: unknown[] }[]): Set<string> {
  const made = new Set(comps.filter((c) => c.documents.length > 0).map((c) => c.id))
  return new Set(layers.flatMap((l) => l.groups.flatMap((g) => g.components
    .filter((c) => made.has(`${l.name}.${c.name}`))
    .map((c) => compKey(l.name, g.name, c.name)))))
}

export type TickState = 'none' | 'some' | 'all'
export function tickState(keys: string[], ticked: ReadonlySet<string>): TickState {
  const n = keys.filter((k) => ticked.has(k)).length
  return n === 0 ? 'none' : n === keys.length ? 'all' : 'some'
}

/** Tick every key, or - when they are all ticked already - untick them. */
export function toggleKeys(keys: string[], ticked: ReadonlySet<string>): Set<string> {
  const next = new Set(ticked)
  const on = tickState(keys, ticked) !== 'all'
  for (const k of keys) {
    if (on) next.add(k)
    else next.delete(k)
  }
  return next
}

/** What the job sends for these ticks, with names as the engine ids them (`Layer1`,
 *  `Layer1.My Sample`, `Layer1.Lib`): whole layers as `layer`, else whole groups as `group`, else
 *  the components. Every component ticked is the whole project (`type: 'project'`); nothing ticked
 *  is `null` - there is nothing to run. */
export function scopeOf(layers: ArchLayer[], ticked: ReadonlySet<string>): JobScope | null {
  const all = allKeys(layers)
  const n = all.filter((k) => ticked.has(k)).length
  if (n === 0) return null
  if (n === all.length) return { type: 'project', names: [] }

  const touched = layers.filter((l) => tickState(layerKeys(l), ticked) !== 'none')
  if (touched.every((l) => tickState(layerKeys(l), ticked) === 'all')) {
    return { type: 'layer', names: touched.map((l) => l.name) }
  }
  const groups = layers.flatMap((l) => l.groups
    .filter((g) => g.components.length > 0 && tickState(groupKeys(l, g), ticked) !== 'none')
    .map((g) => ({ l, g })))
  if (groups.every(({ l, g }) => tickState(groupKeys(l, g), ticked) === 'all')) {
    return { type: 'group', names: groups.map(({ l, g }) => `${l.name}.${g.name}`) }
  }
  const names = layers.flatMap((l) => l.groups.flatMap((g) => g.components
    .filter((c) => ticked.has(compKey(l.name, g.name, c.name)))
    .map((c) => `${l.name}.${c.name}`)))
  return { type: 'component', names: [...new Set(names)] }
}

/** A job's `mode` that adds documents to an existing version (staged generation, a Word file update).
 *  Every other mode is a version's own run: stopping it removes the version (a draft until done). */
const ADDS_DOCUMENTS_MODES = ['export', 'reexport']
export const addsDocuments = (mode: string | null | undefined): boolean =>
  ADDS_DOCUMENTS_MODES.includes(mode ?? '')
