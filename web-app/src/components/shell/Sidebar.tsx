import { NavLink, useParams, useNavigate } from 'react-router-dom'
import { cn } from '../../lib/cn'
import { useUIStore } from '../../store/ui'
import { useAuthStore } from '../../store/auth'
import { useProject } from '../../hooks/useProjects'
import { Icon, BrandMark } from '../ui'
import { APP_NAME, APP_TAGLINE } from '../../constants/branding'

const NAV_ITEMS = [
  { label: 'Overview',  icon: 'home',           to: 'overview'  },
  { label: 'Documents', icon: 'description',    to: 'documents' },
  { label: 'Compare',   icon: 'compare_arrows', to: 'compare'   },
  { label: 'Versions',  icon: 'local_offer',    to: 'versions'  },
  { label: 'Team',      icon: 'group',          to: 'team'      },
]

export function Sidebar() {
  const { projectId } = useParams()
  const navigate = useNavigate()
  const { sidebarCollapsed: collapsed, toggleSidebar } = useUIStore()
  const { user } = useAuthStore()
  const { data: project } = useProject(projectId ?? '')

  return (
    <aside
      className={cn(
        'flex-shrink-0 flex flex-col bg-white border-r border-outline-variant transition-[width] duration-200 ease-[cubic-bezier(.4,0,.2,1)] overflow-hidden',
        collapsed ? 'w-14' : 'w-[220px]',
      )}
      aria-label="Project navigation"
    >
      {/* Brand header */}
      <div
        className={cn(
          'flex items-center border-b border-outline-variant flex-shrink-0',
          collapsed
            ? 'flex-col items-center gap-1.5 px-2 py-2.5'
            : 'justify-between px-4 py-3.5 h-14',
        )}
      >
        <button
          onClick={() => navigate('/projects')}
          className={cn('flex items-center gap-3 min-w-0', collapsed ? 'flex-col' : 'flex-1')}
        >
          <BrandMark size={32} className="flex-shrink-0 text-secondary" />
          {!collapsed && (
            <div className="min-w-0 overflow-hidden text-left">
              <h1 className="text-primary font-bold tracking-tight whitespace-nowrap font-sans text-xl leading-[1.2]">
                {APP_NAME}
              </h1>
              <p className="text-on-surface-variant uppercase whitespace-nowrap mt-0.5 font-mono text-caption font-medium tracking-[0.08em]">
                {APP_TAGLINE}
              </p>
            </div>
          )}
        </button>
        <button
          onClick={toggleSidebar}
          className="w-7 h-7 rounded-lg flex items-center justify-center text-on-surface-variant hover:bg-surface-container transition-colors flex-shrink-0"
          aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          <Icon name={collapsed ? 'chevron_right' : 'chevron_left'} size={18} />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto px-2 py-2" aria-label="Project sections">
        {/* All Projects back link */}
        <button
          onClick={() => navigate('/projects')}
          className={cn(
            'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface transition-colors duration-150 mb-2',
            collapsed && 'justify-center px-0',
          )}
          title={collapsed ? 'All Projects' : undefined}
        >
          <Icon name="arrow_back" size={18} className="flex-shrink-0" />
          {!collapsed && (
            <span className="font-mono text-caption font-medium">All Projects</span>
          )}
        </button>

        {/* Project section label */}
        {!collapsed && project && (
          <p className="px-3 pb-1.5 text-on-surface-variant uppercase truncate text-label font-mono font-semibold tracking-[0.09em]">
            {project.name}
          </p>
        )}

        {/* Nav items */}
        <div className="space-y-0.5">
          {NAV_ITEMS.map(({ label, icon, to }) => (
            <NavLink
              key={to}
              to={`/projects/${projectId}/${to}`}
              title={collapsed ? label : undefined}
              className={({ isActive }) =>
                cn(
                  'nav-item flex items-center gap-2.5 px-3 py-2.5 rounded-lg cursor-pointer transition-colors duration-150',
                  isActive
                    ? cn('nav-active bg-primary text-white', !collapsed && 'border-l-2 border-secondary')
                    : 'nav-default text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface',
                  collapsed && 'justify-center px-0',
                )
              }
            >
              <Icon name={icon} className="flex-shrink-0" />
              {!collapsed && (
                <span className="font-mono text-xs font-medium tracking-[0.02em]">
                  {label}
                </span>
              )}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* Settings */}
      <div className="px-2 pt-2 border-t border-outline-variant flex-shrink-0">
        <button
          className={cn(
            'nav-item w-full flex items-center gap-2.5 px-3 py-2 rounded-lg text-on-surface-variant hover:bg-surface-container-low hover:text-on-surface transition-colors',
            collapsed && 'justify-center px-0',
          )}
          title={collapsed ? 'Settings' : undefined}
        >
          <Icon name="settings" size={18} className="flex-shrink-0" />
          {!collapsed && (
            <span className="font-mono text-xs font-medium">Settings</span>
          )}
        </button>
      </div>

      {/* User info */}
      <div className="px-2 pb-3 pt-1 flex-shrink-0">
        <button
          className={cn(
            'w-full flex items-center gap-3 px-2 py-2 rounded-lg hover:bg-surface-container transition-colors text-left',
            collapsed && 'justify-center px-0',
          )}
        >
          <div className="w-9 h-9 rounded-full bg-secondary-container flex items-center justify-center flex-shrink-0">
            <span className="text-on-secondary-container font-bold text-sm font-sans">
              {user?.initials ?? 'EL'}
            </span>
          </div>
          {!collapsed && (
            <div className="flex-1 min-w-0">
              <p className="text-on-surface truncate leading-tight font-mono text-xs font-medium">
                {user?.name ?? 'Engineering Lead'}
              </p>
              <div className="flex items-center gap-1.5 mt-0.5">
                <span className="w-1.5 h-1.5 rounded-full bg-secondary flex-shrink-0" />
                <p className="text-on-surface-variant uppercase tracking-wide font-mono text-caption font-medium">
                  {user?.role === 'admin' ? 'Admin' : 'Dev'}
                </p>
              </div>
            </div>
          )}
        </button>
      </div>
    </aside>
  )
}
