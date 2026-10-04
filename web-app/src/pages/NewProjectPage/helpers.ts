import type { CoreInput, RepoEntry, UploadKind } from '../../services/api'
import type { ArchLayer, CoreInputs, DraftCore, UploadedFile } from '../../types'

export type Role = 'Admin' | 'Developer'
export interface Member { name?: string; email: string; role: Role }
export interface Comp { id: string; name: string; files: string[]; collapsed: boolean }
export interface Group { id: string; name: string; comps: Comp[]; collapsed: boolean }
/** `coreId`: the core the layer is built for (a `Core.id`, so renaming the core keeps it). */
export interface Layer { id: string; name: string; path: string; groups: Group[]; libPaths: string[]; coreId: string | null; collapsed: boolean }

/** A core: one build of the firmware - its macros (a file, or typed -D lines), data dictionary
 *  and compile commands. `from` is its name in an imported config, which keeps the files the
 *  config names with it after a rename. */
export interface Core {
  id: string
  name: string
  macroMode: 'file' | 'typed'
  macroFile: UploadedFile | null
  macroText: string
  dataDictionary: UploadedFile | null
  compileCommands: UploadedFile | null
  from?: string
}
export type CoreFile = 'macroFile' | 'dataDictionary' | 'compileCommands'

/** Each of a core's files: its upload kind, the extensions the engine reads it from (a data
 *  dictionary is CSV only), and why another file is refused. */
export const CORE_FILES: Record<CoreFile, { kind: UploadKind; exts: string[]; accept: string; types: string; need: string }> = {
  macroFile:       { kind: 'preprocessor_definitions', exts: ['.json', '.csv'], accept: '.json,.csv', types: '.json · .csv', need: 'macros are read from a .json or .csv file' },
  dataDictionary:  { kind: 'data_dictionary', exts: ['.csv'], accept: '.csv', types: '.csv', need: 'the data dictionary must be a .csv file' },
  compileCommands: { kind: 'compile_commands', exts: ['.json'], accept: '.json', types: 'compile_commands.json', need: 'compile commands must be a compile_commands.json' },
}
export const fitsCoreFile = (slot: CoreFile, fileName: string) =>
  CORE_FILES[slot].exts.some((x) => fileName.toLowerCase().endsWith(x))

export const newCore = (id: string, name: string): Core => ({
  id, name, macroMode: 'file', macroFile: null, macroText: '', dataDictionary: null, compileCommands: null,
})

/** The first `CoreN` no core is called. */
export function nextCoreName(cores: Core[]): string {
  const taken = new Set(cores.map((c) => c.name.trim().toLowerCase()))
  let n = 1
  while (taken.has(`core${n}`)) n++
  return `Core${n}`
}

/** Typed macros: one per line, blank lines dropped. */
export const typedDefines = (text: string) => text.split('\n').map((s) => s.trim()).filter(Boolean)

/** The wizard's cores from a config file's (`POST /projects/config/preview`). */
export function draftToCores(cores: DraftCore[], newId: () => string): Core[] {
  return cores.map((c) => ({
    id: newId(),
    name: c.name,
    macroMode: c.macros?.kind === 'typed' ? 'typed' : 'file',
    macroFile: c.macros?.kind === 'file' ? c.macros.file : null,
    macroText: c.macros?.kind === 'typed' ? c.macros.defines.join('\n') : '',
    dataDictionary: c.dataDictionary,
    compileCommands: c.compileCommands,
    from: c.name,
  }))
}

/** The last part of a path, `\` or `/` separated. */
export const baseName = (path: string) => path.split(/[\\/]/).filter(Boolean).pop() ?? path

/** A core file an imported config names and the core does not have yet: the core, the slot, and
 *  the path as the config writes it. */
export interface WantedFile { coreId: string; slot: CoreFile; path: string }

/** The files `want` (the config's paths for core `c`) still asks for: every slot with a path and
 *  no file - macros only while they are a file, not typed. */
export function openWants(c: Core, want: CoreInputs<string | null> | undefined): WantedFile[] {
  if (!want) return []
  const slots: [CoreFile, string | null, boolean][] = [
    ['macroFile', want.macros, c.macroMode === 'file' && !c.macroFile],
    ['dataDictionary', want.dataDictionary, !c.dataDictionary],
    ['compileCommands', want.compileCommands, !c.compileCommands],
  ]
  return slots.filter(([, path, open]) => path && open).map(([slot, path]) => ({ coreId: c.id, slot, path: path! }))
}

const segments = (p: string) => p.split(/[\\/]/).filter((s) => s && s !== '.').map((s) => s.toLowerCase())

/** How many path parts, counted from the end, two paths share - 1 is the file name alone. */
function sharedTail(a: string[], b: string[]): number {
  let n = 0
  while (n < a.length && n < b.length && a[a.length - 1 - n] === b[b.length - 1 - n]) n++
  return n
}

/** Each wanted file's match among the files of a picked folder (`path`: the file's path in the
 *  pick, the picked folder's own name first). The config's paths are on the machine that wrote
 *  it, so only their end can be compared, case aside:
 *  - A file fits when its name and every folder below the picked one end the config's path; the
 *    picked folder's own name may differ (a copy of the inputs). `D:/in/core1/macros.json` fits
 *    `in/core1/macros.json` and `copy/core1/macros.json`, not `in/old/core1/macros.json`. A bare
 *    file name in the config (a downloaded config) fits that name anywhere.
 *  - A file fills only the path that fits it best: picking `core1` alone fills Core1's
 *    `macros.json`, never Core2's. The same path named by several cores shares one file.
 *  Nothing is guessed: no fitting file is `missing`, several - or one that two different paths
 *  fit equally well - is `unsure`. */
export function matchFolder<T extends { path: string }>(wanted: WantedFile[], picked: T[]) {
  const files = picked.map((file) => ({ file, parts: segments(file.path) }))
  const fits = wanted.map((want) => {
    const parts = segments(want.path)
    const scored = files.map((f) => ({ f, n: sharedTail(parts, f.parts) }))
      .filter(({ f, n }) => n > 0 && (parts.length === 1 || n >= f.parts.length - 1))
    const best = Math.max(0, ...scored.map((s) => s.n))
    return { want, key: parts.join('/'), best, hits: scored.filter((s) => s.n === best) }
  })
  // How well the best path fits each file, and which paths fit it that well.
  const top = new Map<(typeof files)[number], { n: number; keys: Set<string> }>()
  for (const x of fits) {
    for (const h of x.hits) {
      const t = top.get(h.f)
      if (!t || h.n > t.n) top.set(h.f, { n: h.n, keys: new Set([x.key]) })
      else if (h.n === t.n) t.keys.add(x.key)
    }
  }
  const out = { found: [] as { want: WantedFile; file: T }[], missing: [] as WantedFile[], unsure: [] as WantedFile[] }
  for (const x of fits) {
    const hits = x.hits.filter((h) => top.get(h.f)!.n === h.n)       // a better path took the rest
    if (!hits.length) out.missing.push(x.want)
    else if (hits.length > 1 || top.get(hits[0].f)!.keys.size > 1) out.unsure.push(x.want)
    else out.found.push({ want: x.want, file: hits[0].f.file })
  }
  return out
}

/** A config's core name → the wizard core it became: by `from`, then by name. */
export function coreIdOf(name: string | null | undefined, cores: Core[]): string | null {
  if (!name) return null
  return (cores.find((c) => c.from === name) ?? cores.find((c) => c.name.trim() === name))?.id ?? null
}

/** What stops the cores being used, one message each - the API refuses the project on the same
 *  (api/services/project_cores.core_problems). */
export function coreProblems(cores: Core[]): string[] {
  const out: string[] = []
  const seen = new Set<string>()
  cores.forEach((c, i) => {
    const name = c.name.trim()
    if (!name) { out.push(`Core ${i + 1} has no name`); return }
    if (seen.has(name.toLowerCase())) out.push(`Two cores are called ${name}`)
    seen.add(name.toLowerCase())
  })
  return out
}

/** A core as the API stores it: typed macros only when typing is chosen, a file otherwise. */
export function coreInput(c: Core): CoreInput {
  const defines = typedDefines(c.macroText)
  const ref = (f: UploadedFile | null) => (f ? { file_id: f.fileId, file_name: f.fileName } : null)
  return {
    name: c.name.trim(),
    macros: c.macroMode === 'typed'
      ? (defines.length ? { mode: 'manual', defines } : null)
      : c.macroFile ? { mode: 'upload', ...ref(c.macroFile)! } : null,
    data_dictionary: ref(c.dataDictionary),
    compile_commands: ref(c.compileCommands),
  }
}

/** The wizard's architecture tree from a config file's layers (`POST /projects/config/preview`),
 *  each layer on the core its config names. Imported layers and components start collapsed: a
 *  real config lists dozens of them, and a collapsed layer still says what it holds. */
export function draftToLayers(layers: ArchLayer[], newId: () => string, cores: Core[] = []): Layer[] {
  return layers.map((l) => ({
    id: newId(),
    name: l.name,
    path: l.path ?? '',
    libPaths: [...(l.libPaths ?? [])],
    coreId: coreIdOf(l.core, cores),
    collapsed: true,
    groups: l.groups.map((g) => ({
      id: newId(),
      name: g.name,
      collapsed: false,
      comps: g.components.map((c) => ({ id: newId(), name: c.name, files: [...(c.files ?? [])], collapsed: true })),
    })),
  }))
}

/** One line for the Review step: the imported `clang` / `views` / `docx` settings. */
export function settingsSummary(settings: Record<string, unknown>): string {
  const parts: string[] = []
  const clang = settings.clang as Record<string, unknown> | undefined
  const args = clang?.clangArgs
  if (Array.isArray(args) && args.length) parts.push(`compiler: ${args.join(' ')}`)
  else if (clang) parts.push('compiler settings')
  const views = settings.views as Record<string, unknown> | undefined
  if (views) {
    parts.push(`flowcharts ${views.flowcharts === true ? 'on' : 'off'}`)
    parts.push(`behaviour diagrams ${views.behaviourDiagram === true ? 'on' : 'off'}`)
  }
  if (settings.docx) parts.push('document settings')
  return parts.join(' · ')
}

/** Every path a component lists → that component's name. */
export function assignmentsOf(layers: Layer[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (const l of layers) for (const g of l.groups) for (const c of g.comps) for (const f of c.files) out[f] = c.name
  return out
}

/** Which component owns `path`: the one that lists it, or one that lists a folder above it. A
 *  config names folders (`Layer1/Sample/Core`), while the file picker lists files — without the
 *  folder check, an imported component's files looked free to give to another component. */
export function ownerOf(path: string, assignments: Record<string, string>): string | undefined {
  if (assignments[path]) return assignments[path]
  for (let i = path.lastIndexOf('/'); i > 0; i = path.lastIndexOf('/', i - 1)) {
    const owner = assignments[path.slice(0, i)]
    if (owner) return owner
  }
  return undefined
}

/** The repository's paths, each a `file` or a `folder`, from the tree `POST /repositories/browse`
 *  returns — what every path of the new project is checked against. */
export type TreeIndex = Map<string, 'file' | 'folder'>
export function indexTree(nodes: RepoEntry[], out: TreeIndex = new Map()): TreeIndex {
  for (const n of nodes) {
    out.set(n.path, n.type === 'folder' ? 'folder' : 'file')
    if (n.children) indexTree(n.children, out)
  }
  return out
}

export interface PathProblem {
  /** Where to show it: the layer, the component for a component's own path, and the path as the
   *  wizard holds it (not normalised), so the page can mark that very entry. */
  layerId: string
  compId?: string
  path: string
  text: string
}

const clean = (p: string) => p.trim().replace(/\\/g, '/').replace(/^(\.\/)+/, '').replace(/\/+$/, '')
const isAbsolute = (p: string) => /^([A-Za-z]:[\\/]|[\\/])/.test(p.trim())

/** Every path in the wizard the branch does not have, and every component that would get no file.
 *  A run reads exactly these paths: one that is not there was skipped without a word, and a
 *  component left with no file stopped the run after the whole parse. So the project is created
 *  only when the list is empty. An absolute lib path is a folder on the server, which the tree cannot show. */
export function pathProblems(layers: Layer[], tree: TreeIndex, branch: string): PathProblem[] {
  const out: PathProblem[] = []
  const on = branch ? `branch \`${branch}\`` : 'the branch'
  let comps = 0
  for (const l of layers) {
    const root = clean(l.path)
    if (!root) out.push({ layerId: l.id, path: l.path, text: `${l.name}: no root folder — pick the layer's folder` })
    else if (root !== '.' && tree.get(root) !== 'folder') {
      out.push({ layerId: l.id, path: l.path, text: `${l.name}: \`${root}\` is not a folder on ${on}` })
    }
    for (const g of l.groups) {
      for (const c of g.comps) {
        comps++
        const at = `${l.name} / ${g.name} / ${c.name}`
        if (!c.files.length) out.push({ layerId: l.id, compId: c.id, path: '', text: `${at}: no files — a run would stop on it` })
        for (const raw of c.files) {
          const f = clean(raw)
          if (!tree.has(f)) {
            out.push({ layerId: l.id, compId: c.id, path: raw, text: `${at}: \`${f}\` is not on ${on}` })
          } else if (root && root !== '.' && f !== root && !f.startsWith(`${root}/`)) {
            out.push({ layerId: l.id, compId: c.id, path: raw, text: `${at}: \`${f}\` is outside the layer's folder \`${root}\`` })
          }
        }
      }
    }
    for (const raw of l.libPaths) {
      const p = clean(raw)
      if (p && !isAbsolute(raw) && tree.get(p) !== 'folder') {
        out.push({ layerId: l.id, path: raw, text: `${l.name}: lib path \`${p}\` is not a folder on ${on}` })
      }
    }
  }
  if (!comps) out.push({ layerId: '', path: '', text: 'No component yet — a run needs at least one' })
  return out
}
