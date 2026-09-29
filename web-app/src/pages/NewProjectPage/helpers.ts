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
