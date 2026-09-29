import type { RepoEntry } from '../../services/api'
import type { ArchLayer } from '../../types'

export type Role = 'Admin' | 'Developer'
export interface Member { name?: string; email: string; role: Role }
export interface Comp { id: string; name: string; files: string[]; collapsed: boolean }
export interface Group { id: string; name: string; comps: Comp[]; collapsed: boolean }
export interface Layer { id: string; name: string; path: string; groups: Group[]; libPaths: string[]; collapsed: boolean }

/** The wizard's architecture tree from a config file's layers (`POST /projects/config/preview`).
 *  Imported components start collapsed: a real config lists dozens of them. */
export function draftToLayers(layers: ArchLayer[], newId: () => string): Layer[] {
  return layers.map((l) => ({
    id: newId(),
    name: l.name,
    path: l.path ?? '',
    libPaths: [...(l.libPaths ?? [])],
    collapsed: false,
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

/** The repository's paths, each a `file` or a `folder`, from the tree `GET /repositories/browse`
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
