import type {
  Project, TeamMember, PageState, UserRole,
  ArchLayer, ArchGroup, ArchComponent, ProjectBuildConfig,
} from '../../types'
import { formatDate, avatarPalette } from '../../lib/format'

export interface ApiProject {
  id: string; name: string; client: string; compliance_standard: string
  status: string; last_run_at: string | null; current_version: string | null
  doc_counts: Record<string, number>; team_count: number; my_role: string | null
  repo_url: string; default_branch?: string; build_config?: Record<string, unknown>
  architecture_layers: unknown[]; created_at: string; updated_at: string
}

const STANDARD_LABELS: Record<string, string> = {
  ISO_26262: 'ISO 26262',
  ASPICE_L2: 'ASPICE L2',
  ASPICE_L3: 'ASPICE L3',
}
export const standardLabel = (s: string): string => STANDARD_LABELS[s] ?? s.replace(/_/g, ' ')

/** ProjectStatus → PageState (only `not_run` differs from the FE vocabulary). */
const projectPageState = (status: string): PageState =>
  status === 'not_run' ? 'never' : (status as PageState)

/** Deterministic icon pick so the row thumbnail is stable per project. */
const PROJECT_ICONS = ['memory', 'sensors', 'tune', 'developer_board', 'bolt', 'dns']
function projectIcon(p: ApiProject): string {
  if (p.status === 'not_run' || p.status === 'stale') return 'warning'
  let h = 0
  for (let i = 0; i < p.id.length; i++) h = (h * 31 + p.id.charCodeAt(i)) >>> 0
  return PROJECT_ICONS[h % PROJECT_ICONS.length]
}

export function mapProject(p: ApiProject): Project {
  const counts = p.doc_counts ?? {}
  const total = counts.total ?? 0
  const approved = counts.approved ?? 0
  const progress = total > 0 ? Math.round((approved / total) * 100) : 0
  return {
    id: p.id,
    name: p.name,
    icon: projectIcon(p),
    client: p.client ?? '',
    repoPath: p.repo_url,
    defaultBranch: p.default_branch ?? '',
    standard: standardLabel(p.compliance_standard),
    latestVersion: p.current_version,
    inReviewCount: counts.in_review ?? 0,
    progress,
    lastRun: formatDate(p.last_run_at),
    // GET /projects exposes only team_count (no member array). Render generic
    // placeholder avatars so the stack/overflow still works. See INTEGRATION_NOTES.
    team: placeholderTeam(p.team_count, p.id),
    architectureLayers: mapArchitecture(p.architecture_layers),
    buildConfig: mapBuildConfig(p.build_config),
    userRole: (p.my_role as UserRole) ?? 'developer',
    pageState: projectPageState(p.status),
  }
}

/**
 * Normalise `architecture_layers` to a typed tree. The shape varies: seed
 * projects store `groups` as a string array; wizard-created projects store
 * `groups: [{name, components:[{name, files}]}]`. Both are handled.
 */
function mapArchitecture(raw: unknown): ArchLayer[] {
  if (!Array.isArray(raw)) return []
  const str = (v: unknown, fallback: string) => (typeof v === 'string' && v ? v : fallback)
  return raw.map((l): ArchLayer => {
    const layer = (l ?? {}) as Record<string, unknown>
    const rawGroups = Array.isArray(layer.groups) ? layer.groups : []
    const groups: ArchGroup[] = rawGroups.map((g): ArchGroup => {
      if (typeof g === 'string') return { name: g, components: [] }
      const grp = (g ?? {}) as Record<string, unknown>
      const rawComps = Array.isArray(grp.components) ? grp.components : []
      const components: ArchComponent[] = rawComps.map((c): ArchComponent => {
        if (typeof c === 'string') return { name: c }
        const comp = (c ?? {}) as Record<string, unknown>
        return {
          name: str(comp.name, 'Component'),
          files: Array.isArray(comp.files) ? comp.files.map(String) : undefined,
        }
      })
      return { name: str(grp.name, 'Group'), components }
    })
    return {
      name: str(layer.name, 'Layer'),
      path: typeof layer.path === 'string' && layer.path ? layer.path : undefined,
      libPaths: Array.isArray(layer.lib_paths) ? layer.lib_paths.map(String) : undefined,
      groups,
    }
  })
}

/** Summarise the (token-free) build config for the overview, defensively. */
function mapBuildConfig(raw: unknown): ProjectBuildConfig {
  const cfg = (raw ?? {}) as Record<string, unknown>
  const out: ProjectBuildConfig = {}
  const defs = cfg.preprocessor_definitions as Record<string, unknown> | undefined
  if (defs && typeof defs === 'object') {
    const mode = typeof defs.mode === 'string' ? defs.mode : 'manual'
    if (mode === 'manual') {
      const list = Array.isArray(defs.defines) ? defs.defines : []
      out.definitions = { mode, count: list.length }
    } else {
      out.definitions = {
        mode,
        count: 0,
        fileName: typeof defs.file_name === 'string' ? defs.file_name : undefined,
      }
    }
  }
  const dd = cfg.data_dictionary as Record<string, unknown> | undefined
  if (dd && typeof dd === 'object' && typeof dd.file_name === 'string') {
    out.dataDictionary = dd.file_name
  }
  return out
}

function placeholderTeam(count: number, seed: string): TeamMember[] {
  return Array.from({ length: Math.max(0, count) }, (_, i) => {
    const pal = avatarPalette(`${seed}:${i}`)
    return {
      id: `${seed}-member-${i}`,
      name: 'Team member',
      initials: '',
      email: '',
      role: 'developer' as UserRole,
      lastActive: '',
      avatarColor: pal.bg,
      avatarTextColor: pal.text,
    }
  })
}
