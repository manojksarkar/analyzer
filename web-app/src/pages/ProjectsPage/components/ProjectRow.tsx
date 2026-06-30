import { Dropdown, DropdownTrigger, DropdownContent, Icon, toast } from '../../../components/ui'
import { useDeleteProject } from '../../../hooks/useProjects'
import { cn } from '../../../lib/cn'
import type { Project, TeamMember } from '../../../types'

/* ─── Avatar stack ─────────────────────────────────────────────────── */
function AvatarStack({ members, max = 3 }: { members: TeamMember[]; max?: number }) {
  if (members.length === 0) return null
  const visible = members.slice(0, max)
  const overflow = members.length - max
  return (
    <div className="flex items-center" aria-label={`${members.length} member${members.length !== 1 ? 's' : ''}`}>
      {visible.map((m, i) => (
        <div
          key={m.id}
          title={m.name}
          className="w-[26px] h-[26px] rounded-full border-2 border-white inline-flex items-center justify-center relative flex-shrink-0 font-sans text-micro font-bold"
          // eslint-disable-next-line no-restricted-syntax -- avatar colour + stacking offset are data-driven
          style={{ background: m.avatarColor, color: m.avatarTextColor, zIndex: visible.length - i, marginLeft: i > 0 ? -8 : 0 }}
          aria-hidden
        >
          {m.initials}
        </div>
      ))}
      {overflow > 0 && (
        <div
          title={`+${overflow} more`}
          className="w-[26px] h-[26px] rounded-full border-2 border-white inline-flex items-center justify-center relative flex-shrink-0 font-sans text-micro font-bold bg-[#f3f4f6] text-on-surface-variant z-0 -ml-2"
          aria-label={`+${overflow} more`}
        >
          +{overflow}
        </div>
      )}
    </div>
  )
}

/* ─── Project icon thumbnail ────────────────────────────────────────── */
function ProjectIcon({ project }: { project: Project }) {
  const isStale = project.pageState === 'never' || project.pageState === 'stale'
  const isAdmin = project.userRole === 'admin'

  if (project.icon === 'warning' || isStale) {
    return (
      <div className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 bg-[#fff8e6] border border-amber">
        <Icon name="warning" size={18} className="text-[#d97706]" />
      </div>
    )
  }
  if (isAdmin) {
    return (
      <div className="w-9 h-9 rounded-lg bg-secondary-container flex items-center justify-center flex-shrink-0">
        <Icon name={project.icon} size={18} fill className="text-secondary" />
      </div>
    )
  }
  return (
    <div className="w-9 h-9 rounded-lg bg-surface-container-low border border-outline-variant flex items-center justify-center flex-shrink-0">
      <Icon name={project.icon} size={18} className="text-on-surface-variant" />
    </div>
  )
}

/* ─── Role badge (inline pill) ──────────────────────────────────────── */
function RolePill({ role }: { role: 'admin' | 'developer' }) {
  const isAdmin = role === 'admin'
  return (
    <span
      className={cn(
        'font-mono text-micro font-bold rounded-full tracking-[0.04em] uppercase px-[7px] py-px',
        isAdmin ? 'bg-surface-container text-secondary' : 'bg-[#f3f4f6] text-on-surface-variant',
      )}
    >
      {isAdmin ? 'ADMIN' : 'DEV'}
    </span>
  )
}

/* ─── Standard badge ────────────────────────────────────────────────── */
function StandardBadge({ standard }: { standard: string }) {
  const isAspiceL3 = standard === 'ASPICE L3'
  return (
    <span
      className={cn(
        'font-mono text-label font-bold px-[7px] py-0.5 rounded-[3px] uppercase whitespace-nowrap',
        isAspiceL3 ? 'bg-[#e5f7f0] text-[#00a572]' : 'bg-surface-container text-secondary',
      )}
    >
      {standard}
    </span>
  )
}

/* ─── Version badge ─────────────────────────────────────────────────── */
function VersionBadge({ version }: { version: string | null }) {
  if (!version) return <span className="text-on-surface-variant font-mono text-caption">—</span>
  return (
    <span className="font-mono text-label font-bold bg-[#f3f4f6] text-on-surface-variant border border-outline-variant px-[7px] py-0.5 rounded-[3px]">
      {version}
    </span>
  )
}

/* ─── Project row ───────────────────────────────────────────────────── */
export function ProjectRow({ project, onNavigate }: { project: Project; onNavigate: (id: string) => void }) {
  // Role is per-project now (project.userRole from the API's my_role).
  const isAdmin = project.userRole === 'admin'
  const isStale = project.pageState === 'never' || project.pageState === 'stale'
  const deleteProject = useDeleteProject()

  const onDelete = () => {
    if (window.confirm(`Delete "${project.name}"? This cannot be undone.`)) {
      deleteProject.mutate(project.id)
    }
  }

  const adminItems = [
    { label: 'Settings', icon: 'settings',     onClick: () => onNavigate(project.id) },
    { label: 'Archive',  icon: 'archive',      onClick: () => toast.info('Archive', 'Archiving is not available yet.') },
    { label: 'Delete',   icon: 'delete',       variant: 'danger' as const, onClick: onDelete },
  ]
  const devItems = [
    { label: 'View Project', icon: 'open_in_new', onClick: () => onNavigate(project.id) },
  ]

  return (
    <tr
      className={cn('project-row border-b border-outline-variant last:border-0 cursor-pointer', isStale && 'bg-[#fffcf5]')}
      onClick={() => onNavigate(project.id)}
    >
      {/* Name + icon */}
      <td className="px-5 py-3.5">
        <div className="flex items-center gap-3">
          <ProjectIcon project={project} />
          <div>
            <p className="text-on-surface flex items-center gap-2 font-mono text-xs font-medium">
              {project.name}
              <RolePill role={project.userRole} />
            </p>
          </div>
        </div>
      </td>

      {/* Standard */}
      <td className="px-4 py-3.5">
        <StandardBadge standard={project.standard} />
      </td>

      {/* Latest version */}
      <td className="px-4 py-3.5">
        <VersionBadge version={project.latestVersion} />
      </td>

      {/* In Review — right-aligned, blue */}
      <td className="text-right px-4 py-3.5">
        {project.inReviewCount > 0 ? (
          <span className="text-secondary font-mono text-xs font-semibold">{project.inReviewCount}</span>
        ) : (
          <span className="text-on-surface-variant font-mono text-xs">—</span>
        )}
      </td>

      {/* Progress */}
      <td className="px-4 py-3.5 w-40">
        <div className="flex items-center gap-2">
          <div className="progress-track flex-1">
            {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
            <div className="progress-fill bg-on-tertiary-container" style={{ width: `${project.progress}%` }} />
          </div>
          <span className="text-on-surface-variant font-mono text-caption w-7 text-right">{project.progress}%</span>
        </div>
      </td>

      {/* Last Run */}
      <td className="px-4 py-3.5 whitespace-nowrap">
        {project.lastRun ? (
          <span className={cn('font-mono text-caption', isStale ? 'text-[#d97706]' : 'text-on-surface-variant')}>{project.lastRun}</span>
        ) : (
          <span className="text-on-surface-variant font-mono text-caption">—</span>
        )}
      </td>

      {/* Team */}
      <td className="px-4 py-3.5">
        {project.team.length === 0 ? (
          <button
            onClick={(e) => e.stopPropagation()}
            className="inline-flex items-center gap-1 px-[9px] py-[3px] border-[1.5px] border-dashed border-outline-variant rounded-full bg-transparent cursor-pointer text-outline font-mono text-label"
            aria-label="Add team members"
          >
            <Icon name="person_add" size={12} />
            Add
          </button>
        ) : (
          <AvatarStack members={project.team} max={3} />
        )}
      </td>

      {/* Row menu */}
      <td className="px-4 py-3.5 relative w-11" onClick={(e) => e.stopPropagation()}>
        <Dropdown>
          <DropdownTrigger asChild>
            <button
              className="p-1 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant"
              aria-label={`Actions for ${project.name}`}
            >
              <Icon name="more_vert" size={18} />
            </button>
          </DropdownTrigger>
          <DropdownContent items={isAdmin ? adminItems : devItems} />
        </Dropdown>
      </td>
    </tr>
  )
}
