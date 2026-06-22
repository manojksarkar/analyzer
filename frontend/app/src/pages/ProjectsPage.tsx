import { useNavigate } from 'react-router-dom'
import { useProjects } from '../hooks/useProjects'
import { useAuthStore } from '../store/auth'
import { Dropdown, DropdownTrigger, DropdownContent, TableSkeleton } from '../components/ui'
import type { Project, TeamMember } from '../types'

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
          style={{
            width: 26, height: 26, borderRadius: '50%',
            background: m.avatarColor, color: m.avatarTextColor,
            border: '2px solid white', display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center',
            position: 'relative', zIndex: visible.length - i,
            flexShrink: 0, marginLeft: i > 0 ? -8 : 0,
            fontFamily: 'Inter', fontSize: 9, fontWeight: 700,
          }}
          aria-hidden
        >
          {m.initials}
        </div>
      ))}
      {overflow > 0 && (
        <div
          title={`+${overflow} more`}
          style={{
            width: 26, height: 26, borderRadius: '50%',
            background: '#f3f4f6', color: '#44474c',
            border: '2px solid white', display: 'inline-flex',
            alignItems: 'center', justifyContent: 'center',
            position: 'relative', zIndex: 0, flexShrink: 0,
            marginLeft: -8, fontFamily: 'Inter', fontSize: 9, fontWeight: 700,
          }}
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
      <div
        className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0"
        style={{ background: '#fff8e6', border: '1px solid #f59e0b' }}
      >
        <span className="material-symbols-outlined" style={{ fontSize: 18, color: '#d97706' }} aria-hidden>warning</span>
      </div>
    )
  }
  if (isAdmin) {
    return (
      <div className="w-9 h-9 rounded-lg bg-secondary-container flex items-center justify-center flex-shrink-0">
        <span
          className="material-symbols-outlined sym-fill text-secondary"
          style={{ fontSize: 18 }}
          aria-hidden
        >
          {project.icon}
        </span>
      </div>
    )
  }
  return (
    <div className="w-9 h-9 rounded-lg bg-surface-container-low border border-outline-variant flex items-center justify-center flex-shrink-0">
      <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 18 }} aria-hidden>
        {project.icon}
      </span>
    </div>
  )
}

/* ─── Role badge (inline pill) ──────────────────────────────────────── */
function RolePill({ role }: { role: 'admin' | 'developer' }) {
  const isAdmin = role === 'admin'
  return (
    <span
      style={{
        fontFamily: "'JetBrains Mono'", fontSize: 9, fontWeight: 700,
        background: isAdmin ? '#e5eeff' : '#f3f4f6',
        color: isAdmin ? '#0058be' : '#44474c',
        padding: '1px 7px', borderRadius: 99, letterSpacing: '0.04em',
        textTransform: 'uppercase',
      }}
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
      style={{
        fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700,
        background: isAspiceL3 ? '#e5f7f0' : '#e5eeff',
        color: isAspiceL3 ? '#00a572' : '#0058be',
        padding: '2px 7px', borderRadius: 3, textTransform: 'uppercase',
        whiteSpace: 'nowrap',
      }}
    >
      {standard}
    </span>
  )
}

/* ─── Version badge ─────────────────────────────────────────────────── */
function VersionBadge({ version }: { version: string | null }) {
  if (!version) return <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>—</span>
  return (
    <span
      style={{
        fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700,
        background: '#f3f4f6', color: '#44474c',
        border: '1px solid #c4c6cd',
        padding: '2px 7px', borderRadius: 3,
      }}
    >
      {version}
    </span>
  )
}

/* ─── Project row ───────────────────────────────────────────────────── */
function ProjectRow({ project, onNavigate }: { project: Project; onNavigate: (id: string) => void }) {
  const user = useAuthStore((s) => s.user)
  const isAdmin = user?.role === 'admin'
  const isStale = project.pageState === 'never' || project.pageState === 'stale'

  const adminItems = [
    { label: 'Settings', icon: 'settings',     onClick: () => {} },
    { label: 'Archive',  icon: 'archive',      onClick: () => {} },
    { label: 'Delete',   icon: 'delete',       variant: 'danger' as const, onClick: () => {} },
  ]
  const devItems = [
    { label: 'View Project', icon: 'open_in_new', onClick: () => onNavigate(project.id) },
  ]

  return (
    <tr
      className="project-row border-b border-outline-variant last:border-0 cursor-pointer"
      style={isStale ? { background: '#fffcf5' } : undefined}
      onClick={() => onNavigate(project.id)}
    >
      {/* Name + icon */}
      <td className="px-5 py-3.5">
        <div className="flex items-center gap-3">
          <ProjectIcon project={project} />
          <div>
            <p
              className="text-on-surface flex items-center gap-2"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}
            >
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
          <span className="text-secondary" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 600 }}>
            {project.inReviewCount}
          </span>
        ) : (
          <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>—</span>
        )}
      </td>

      {/* Progress */}
      <td className="px-4 py-3.5" style={{ width: 160 }}>
        <div className="flex items-center gap-2">
          <div className="progress-track flex-1">
            <div className="progress-fill bg-on-tertiary-container" style={{ width: `${project.progress}%` }} />
          </div>
          <span
            className="text-on-surface-variant"
            style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, width: 28, textAlign: 'right' }}
          >
            {project.progress}%
          </span>
        </div>
      </td>

      {/* Last Run */}
      <td className="px-4 py-3.5" style={{ whiteSpace: 'nowrap' }}>
        {project.lastRun ? (
          <span
            style={{
              fontFamily: "'JetBrains Mono'", fontSize: 11,
              color: isStale ? '#d97706' : '#44474c',
            }}
          >
            {project.lastRun}
          </span>
        ) : (
          <span className="text-on-surface-variant" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>—</span>
        )}
      </td>

      {/* Team */}
      <td className="px-4 py-3.5">
        {project.team.length === 0 ? (
          <button
            onClick={(e) => e.stopPropagation()}
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 4,
              padding: '3px 9px', border: '1.5px dashed #c4c6cd',
              borderRadius: 99, background: 'transparent', cursor: 'pointer',
              color: '#74777d', fontFamily: "'JetBrains Mono'", fontSize: 10,
            }}
            aria-label="Add team members"
          >
            <span className="material-symbols-outlined" style={{ fontSize: 12 }} aria-hidden>person_add</span>
            Add
          </button>
        ) : (
          <AvatarStack members={project.team} max={3} />
        )}
      </td>

      {/* Row menu */}
      <td className="px-4 py-3.5" style={{ position: 'relative', width: 44 }} onClick={(e) => e.stopPropagation()}>
        <Dropdown>
          <DropdownTrigger asChild>
            <button
              className="p-1 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant"
              aria-label={`Actions for ${project.name}`}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden>more_vert</span>
            </button>
          </DropdownTrigger>
          <DropdownContent items={isAdmin ? adminItems : devItems} />
        </Dropdown>
      </td>
    </tr>
  )
}

/* ─── Page ──────────────────────────────────────────────────────────── */
export function ProjectsPage() {
  const navigate = useNavigate()
  const { data: projects, isLoading, isError } = useProjects()
  const { user, signOut } = useAuthStore()

  return (
    <div className="h-screen flex flex-col overflow-hidden relative">
      {/* Dot grid background */}
      <div
        className="fixed inset-0 pointer-events-none -z-10 opacity-[0.025]"
        style={{
          backgroundImage: 'radial-gradient(#041627 0.5px, transparent 0.5px)',
          backgroundSize: '24px 24px',
        }}
        aria-hidden
      />

      {/* ── Top bar ── */}
      <header className="h-14 flex-shrink-0 flex items-center justify-between px-6 bg-white border-b border-outline-variant z-40">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 bg-secondary rounded-lg flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined sym-fill text-white" style={{ fontSize: 18 }} aria-hidden>account_tree</span>
          </div>
          <div>
            <h1
              className="text-primary font-bold tracking-tight"
              style={{ fontFamily: 'Inter', fontSize: 15, lineHeight: 1.2 }}
            >
              [PRODUCT NAME]
            </h1>
            <p
              className="text-on-surface-variant uppercase mt-0.5"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.08em' }}
            >
              Automotive Tier 1
            </p>
          </div>
        </div>

        {/* Right */}
        <div className="flex items-center gap-0.5">
          <button className="relative p-2 hover:bg-surface-container rounded-lg transition-colors" aria-label="Notifications">
            <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 22 }} aria-hidden>notifications</span>
            <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-error rounded-full border-2 border-white" aria-hidden />
          </button>
          <button className="p-2 hover:bg-surface-container rounded-lg transition-colors" aria-label="Help">
            <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 22 }} aria-hidden>help</span>
          </button>

          <div className="w-px h-5 bg-outline-variant mx-1.5" aria-hidden />

          <Dropdown>
            <DropdownTrigger asChild>
              <button
                className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-container rounded-lg transition-colors"
                aria-label={`User menu — ${user?.name}`}
              >
                <div className="w-7 h-7 rounded-full bg-secondary-container flex items-center justify-center">
                  <span className="text-on-secondary-container font-bold text-xs" style={{ fontFamily: 'Inter' }}>
                    {user?.initials ?? 'EL'}
                  </span>
                </div>
                <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 16 }} aria-hidden>expand_more</span>
              </button>
            </DropdownTrigger>
            <DropdownContent
              items={[
                { label: 'Profile',  icon: 'person', onClick: () => {} },
                { label: 'Sign out', icon: 'logout', variant: 'danger', onClick: signOut },
              ]}
            />
          </Dropdown>
        </div>
      </header>

      {/* ── Scrollable content ── */}
      <div className="flex-1 overflow-y-auto">
        <div className="px-6 py-6 mx-auto" style={{ maxWidth: 1280 }}>

          {/* Page heading */}
          <div className="flex items-center justify-between mb-5">
            <div>
              <h1
                className="text-on-surface"
                style={{ fontFamily: 'Inter', fontSize: 24, fontWeight: 600, lineHeight: '32px', letterSpacing: '-0.01em' }}
              >
                Projects
              </h1>
              <p className="text-on-surface-variant mt-0.5" style={{ fontSize: 12 }}>
                {isLoading ? 'Loading…' : `System-wide · ${projects?.length ?? 0} project${projects?.length !== 1 ? 's' : ''}`}
              </p>
            </div>
            <button
              onClick={() => navigate('/projects/new')}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors"
              style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 700, letterSpacing: '0.04em' }}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>add</span>
              NEW PROJECT
            </button>
          </div>

          {/* Projects table */}
          <div className="bg-white border border-outline-variant rounded-xl overflow-hidden mb-6">
            {isError ? (
              <div className="flex items-center justify-center h-32 text-sm text-on-surface-variant">
                Failed to load projects.
              </div>
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    {[
                      { label: 'Name',      cls: 'text-left px-5 py-3' },
                      { label: 'Standard',  cls: 'text-left px-4 py-3' },
                      { label: 'Latest',    cls: 'text-left px-4 py-3' },
                      { label: 'In Review', cls: 'text-right px-4 py-3' },
                      { label: 'Progress',  cls: 'px-4 py-3', style: { width: 160 } },
                      { label: 'Last Run',  cls: 'text-left px-4 py-3' },
                      { label: 'Team',      cls: 'text-left px-4 py-3' },
                      { label: '',          cls: 'px-4 py-3', style: { width: 44 } },
                    ].map(({ label, cls, style }) => (
                      <th
                        key={label}
                        className={cls}
                        style={{
                          fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500,
                          color: '#44474c', textTransform: 'uppercase', letterSpacing: '0.07em',
                          ...style,
                        }}
                      >
                        {label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {isLoading
                    ? null
                    : projects?.map((project) => (
                        <ProjectRow
                          key={project.id}
                          project={project}
                          onNavigate={(id) => navigate(`/projects/${id}/overview`)}
                        />
                      ))}
                </tbody>
              </table>
            )}
            {isLoading && <TableSkeleton rows={5} cols={8} />}
          </div>
        </div>
      </div>
    </div>
  )
}
