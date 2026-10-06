import type { ArchLayer, ComponentState, VersionComponent, VersionComponents, VersionRun } from '../types'

/* Staged generation's pure rules: a version's components and the state of their documents
   (GET …/versions/{vid}/components), as the Generation banner and the Components drawer show them
   on the Overview and the Documents page. */

/** A component that has its documents: up to date, or out of date (a layer added since). */
export const HAS_DOCUMENTS = new Set<ComponentState>(['generated', 'stale'])
export const hasDocuments = (c: VersionComponent) => HAS_DOCUMENTS.has(c.state)

/** The version's components per layer, in the order the server gives them. */
export function componentsByLayer(comps: VersionComponent[]): [string, VersionComponent[]][] {
  const out = new Map<string, VersionComponent[]>()
  for (const c of comps) {
    const list = out.get(c.layer) ?? []
    list.push(c)
    out.set(c.layer, list)
  }
  return [...out.entries()]
}

/** A component of a layer the model lacks yet: Generate adds that layer first (parse + descriptions). */
export const addsLayer = (c: VersionComponent) => !c.inModel && !c.layerParsed

/** Components an admin can ask for: with no documents (never asked for, or the run that was making
 *  them failed or stopped), of the model — or of a layer it lacks, which Generate adds. One with
 *  documents whose update failed, or a stale one, is not: making it again is an update of its Word
 *  files. One
 *  outside the model whose layer IS parsed (configured, no source found) cannot be made at all. */
export const PICKABLE_STATES = new Set<ComponentState>(['not_requested', 'failed', 'stopped'])
export const pickable = (c: VersionComponent) =>
  (c.inModel || addsLayer(c)) && PICKABLE_STATES.has(c.state) && c.documents.length === 0

/** Configured, its layer parsed, no source found: no run can make its documents. */
const unmakeable = (c: VersionComponent) => !c.inModel && c.layerParsed && !hasDocuments(c)

/** The layers Generate would add for `comps` (those outside the model), in order. */
export const layersAdded = (comps: VersionComponent[]): string[] =>
  [...new Set(comps.filter(addsLayer).map((c) => c.layer))].sort()

/** Under a layer the model lacks: what Generate does for its components, and what it costs. */
export function layerNote(layer: string, comps: VersionComponent[]): string | null {
  const list = comps.filter((c) => c.layer === layer)
  if (!list.length || !list.every(addsLayer)) return null
  const modelLayers = [...new Set(comps.filter((c) => c.inModel).map((c) => c.layer))].filter(Boolean)
  const others = modelLayers.length ? `${modelLayers.join(', ')} documents` : 'documents of the other layers'
  return `Not in this version's model yet — Generate adds layer ${layer} (parse + descriptions for that layer; ${others} may be marked stale)`
}

/* Which Word files are out of date, and their update, are R9's (lib/wordFiles.ts): the banner's
   second row reads it, not the components' `stale` state. */

/* ── The Generation banner ─────────────────────────────────────────────────────────────── */

/** What a run is doing, by its command (or the web job's mode before its run has started). */
export function runVerb(command: string | null | undefined): string {
  if (command === 'reexport') return 'Updating Word files'
  if (command === 'resume') return 'Resuming document generation'
  return 'Generating documents'
}

/** The engine's progress stages (`ProgressReporter(…)`, `version_run.progress(…)`), in words. */
const STAGE_WORDS: Record<string, string> = {
  'parser:parse': 'parsing the code',
  'parser:calls+globals': 'reading calls and globals',
  'LLM-description': 'writing descriptions',
  'LLM-description-pass1': 'writing descriptions',
  'LLM-description-pass2': 'writing descriptions, second pass',
  'LLM-global': 'describing globals',
  'LLM-rich-global': 'describing globals',
  'LLM-behaviour-names': 'naming inputs and outputs',
  flowcharts: 'drawing flowcharts',
  'flowcharts:PNG': 'drawing flowchart pictures',
  unitDiagrams: 'drawing unit diagrams',
  behaviourDiagram: 'drawing behaviour diagrams',
  docx_exporter: 'writing Word files',
}

/** "drawing flowcharts, 38 of 112" — the live run's stage; '' when it reports none. */
export function runActivity(run: Pick<VersionRun, 'stage' | 'done' | 'total'> | null | undefined): string {
  if (!run?.stage) return ''
  const words = STAGE_WORDS[run.stage] ?? run.stage.replace(/[-_:]+/g, ' ').trim()
  return run.total ? `${words}, ${run.done ?? 0} of ${run.total}` : words
}

export type GenerationRow =
  /** A run, or a web job, is at work on the version. */
  | { kind: 'running'; verb: string; activity: string; startedAt: string | null }
  /** Its run stopped before it finished (`stopped`), or finished with components cut short. */
  | { kind: 'stopped'; at: string | null; cutShort: number }
  /** Nothing at work, and `missing` components have no documents yet. */
  | { kind: 'missing'; missing: number }

export interface GenerationSummary {
  total: number
  /** Components with documents (up to date or out of date). */
  withDocs: number
  /** The banner's first row; null when none applies. */
  row: GenerationRow | null
  /** Components out of date (the second row). */
  stale: number
}

/** The banner's rows, first rule that applies: a run at work; a run stopped (or components cut
 *  short); components without documents. A component no run can make (configured, no source)
 *  never holds the banner open. */
export function generationSummary(data: VersionComponents | undefined): GenerationSummary | null {
  if (!data || data.components.length === 0) return null
  const comps = data.components
  const withDocs = comps.filter(hasDocuments).length
  const stale = comps.filter((c) => c.state === 'stale').length
  const cutShort = comps.filter((c) => c.inModel && (c.state === 'stopped' || c.state === 'failed')).length
  const missing = comps.filter((c) => !hasDocuments(c) && !unmakeable(c)).length
  const { run, job } = data
  let row: GenerationRow | null = null
  if (run?.alive || job) {
    const live = run?.alive ? run : null
    row = {
      kind: 'running',
      verb: runVerb(live ? live.command : job?.mode),
      activity: runActivity(live),
      startedAt: live?.startedAt ?? null,
    }
  } else if (run?.stopped || cutShort > 0) {
    row = { kind: 'stopped', at: run?.stopped ? run.progressAt ?? run.startedAt : null, cutShort }
  } else if (missing > 0) {
    row = { kind: 'missing', missing }
  }
  return { total: comps.length, withDocs, row, stale }
}

/** Whether the banner shows: components exist and a row applies — something without documents, at
 *  work, stopped, or out of date. `needsModel` (a version with no documents yet): only when it has a
 *  model to make documents from — without one, Generate has nothing to start from. */
export function generationBannerShown(data: VersionComponents | undefined, opts: { needsModel?: boolean } = {}): boolean {
  const s = generationSummary(data)
  if (!s || (!s.row && s.stale === 0)) return false
  return !opts.needsModel || !!data?.components.some((c) => c.inModel)
}

/* ── The Components drawer ─────────────────────────────────────────────────────────────── */

export interface ComponentGroup {
  /** null: no configuration names its group — its chips sit straight under the layer. */
  name: string | null
  comps: VersionComponent[]
  /** Its components, the filters aside. */
  size: number
}

export interface ComponentLayer {
  layer: string
  /** Every component of the layer (the filters aside): its counts. */
  all: VersionComponent[]
  groups: ComponentGroup[]
}

/** A component's output-folder name from a configured one: spaces become `-` (`Sample Core` ↔
 *  `Sample-Core`), as the engine names the folder. */
const folder = (s: string) => s.trim().replace(/ /g, '-')

/** A component's group: the API's (`group`, from the version's own configuration), else the
 *  project's architecture matched by layer and name. null when neither names one. */
export function groupOf(c: VersionComponent, layers: ArchLayer[] = []): string | null {
  if (c.group) return c.group
  const layer = layers.find((l) => folder(l.name) === folder(c.layer))
  const g = layer?.groups.find((x) => x.components.some((k) => folder(k.name) === c.name))
  return g?.name ?? null
}

/** The order the project's architecture lists names in; names it lacks after, as they come. */
function inOrder<T>(items: T[], key: (t: T) => string, order: string[]): T[] {
  const rank = (t: T) => {
    const i = order.indexOf(key(t))
    return i < 0 ? order.length : i
  }
  return items.map((t, i) => [t, i] as const)
    .sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1])
    .map(([t]) => t)
}

/** Layer → group → components, as the Architecture view lays them out: layers and groups in the
 *  project's order, components in the server's (by name). Ungrouped components come first. */
export function componentTree(comps: VersionComponent[], layers: ArchLayer[] = []): ComponentLayer[] {
  const tree = componentsByLayer(comps).map(([layer, all]) => {
    const groups = new Map<string | null, VersionComponent[]>()
    for (const c of all) {
      const g = groupOf(c, layers)
      groups.set(g, [...(groups.get(g) ?? []), c])
    }
    const configured = layers.find((l) => folder(l.name) === folder(layer))?.groups.map((g) => g.name) ?? []
    const list = [...groups.entries()].map(([name, cs]) => ({ name, comps: cs, size: cs.length }))
    return {
      layer,
      all,
      groups: [...list.filter((g) => g.name === null), ...inOrder(list.filter((g) => g.name !== null), (g) => g.name as string, configured)],
    }
  })
  return inOrder(tree, (l) => folder(l.layer), layers.map((l) => folder(l.name)))
}

/** The drawer's filters: a name search (case-insensitive; `-` matches a space) and "Without
 *  documents" (hides the components that have theirs). Empty groups and layers go. */
export function filterTree(tree: ComponentLayer[], query: string, withoutDocsOnly: boolean): ComponentLayer[] {
  const q = query.trim().toLowerCase()
  const keep = (c: VersionComponent) =>
    (!withoutDocsOnly || !hasDocuments(c))
    && (!q || c.name.toLowerCase().includes(q) || c.name.replace(/-/g, ' ').toLowerCase().includes(q))
  return tree
    .map((l) => ({ ...l, groups: l.groups.map((g) => ({ ...g, comps: g.comps.filter(keep) })).filter((g) => g.comps.length) }))
    .filter((l) => l.groups.length)
}
