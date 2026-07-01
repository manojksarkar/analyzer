import { useNavigate } from 'react-router-dom'
import { useProjects } from '../../hooks/useProjects'
import { useAuthStore } from '../../store/auth'
import { Dropdown, DropdownTrigger, DropdownContent, Icon, TableSkeleton, toast } from '../../components/ui'
import { NotificationBell } from '../../components/shell/NotificationBell'
import { ProjectRow } from './components/ProjectRow'
import { ProjectsEmptyState } from './components/ProjectsEmptyState'
import { APP_NAME, APP_TAGLINE } from '../../constants/branding'

/* Column headers — width baked into the class so no inline style is needed. */
const COLUMNS = [
  { label: 'Name',      cls: 'text-left px-5 py-3' },
  { label: 'Standard',  cls: 'text-left px-4 py-3' },
  { label: 'Latest',    cls: 'text-left px-4 py-3' },
  { label: 'In Review', cls: 'text-right px-4 py-3' },
  { label: 'Progress',  cls: 'px-4 py-3 w-40' },
  { label: 'Last Run',  cls: 'text-left px-4 py-3' },
  { label: 'Team',      cls: 'text-left px-4 py-3' },
  { label: '',          cls: 'px-4 py-3 w-11' },
]

export function ProjectsPage() {
  const navigate = useNavigate()
  const { data: projects, isLoading, isError } = useProjects()
  const { user, signOut } = useAuthStore()
  const isEmpty = !isLoading && !isError && (projects?.length ?? 0) === 0
  const requestAccess = () =>
    toast.info('Request access', 'Ask your workspace administrator to add you to a project.')

  return (
    <div className="h-screen flex flex-col overflow-hidden relative">
      {/* Dot grid background */}
      <div
        className="fixed inset-0 pointer-events-none -z-10 opacity-[0.025]"
        // eslint-disable-next-line no-restricted-syntax -- decorative dot-grid pattern (awkward as a utility)
        style={{ backgroundImage: 'radial-gradient(#041627 0.5px, transparent 0.5px)', backgroundSize: '24px 24px' }}
        aria-hidden
      />

      {/* ── Top bar ── */}
      <header className="h-14 flex-shrink-0 flex items-center justify-between px-6 bg-white border-b border-outline-variant z-40">
        {/* Brand */}
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-secondary rounded-lg flex items-center justify-center flex-shrink-0">
            <Icon name="account_tree" size={20} fill className="text-white" />
          </div>
          <div>
            <h1 className="text-primary font-bold tracking-tight font-sans text-xl leading-[1.2]">
              {APP_NAME}
            </h1>
            <p className="text-on-surface-variant uppercase mt-0.5 font-mono text-caption font-medium tracking-[0.08em]">
              {APP_TAGLINE}
            </p>
          </div>
        </div>

        {/* Right */}
        <div className="flex items-center gap-0.5">
          <NotificationBell />
          <button className="p-2 hover:bg-surface-container rounded-lg transition-colors" aria-label="Help">
            <Icon name="help" size={22} className="text-on-surface-variant" />
          </button>

          <div className="w-px h-5 bg-outline-variant mx-1.5" aria-hidden />

          <Dropdown>
            <DropdownTrigger asChild>
              <button
                className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-container rounded-lg transition-colors"
                aria-label={`User menu — ${user?.name}`}
              >
                <div className="w-7 h-7 rounded-full bg-secondary-container flex items-center justify-center">
                  <span className="text-on-secondary-container font-bold text-xs font-sans">
                    {user?.initials ?? 'EL'}
                  </span>
                </div>
                <Icon name="expand_more" size={16} className="text-on-surface-variant" />
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
        <div className="px-6 py-6 mx-auto max-w-[1280px]">

          {/* Page heading */}
          <div className="flex items-center justify-between mb-5">
            <div>
              <h1 className="text-on-surface font-sans text-2xl font-semibold leading-[32px] tracking-[-0.01em]">
                Projects
              </h1>
              <p className="text-on-surface-variant mt-0.5 text-xs">
                {isLoading ? 'Loading…' : `System-wide · ${projects?.length ?? 0} project${projects?.length !== 1 ? 's' : ''}`}
              </p>
            </div>
            {!isEmpty && (
              <div className="flex items-center gap-2">
                <button
                  onClick={requestAccess}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-white border border-outline-variant hover:bg-surface-container-low text-on-surface rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em]"
                >
                  <Icon name="lock" size={14} />
                  REQUEST ACCESS
                </button>
                <button
                  onClick={() => navigate('/projects/new')}
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em]"
                >
                  <Icon name="add" size={14} />
                  NEW PROJECT
                </button>
              </div>
            )}
          </div>

          {/* Projects table */}
          <div className="bg-white border border-outline-variant rounded-xl overflow-hidden mb-6">
            {isError ? (
              <div className="flex items-center justify-center h-32 text-sm text-on-surface-variant">
                Failed to load projects.
              </div>
            ) : isEmpty ? (
              <ProjectsEmptyState
                onNewProject={() => navigate('/projects/new')}
                onRequestAccess={requestAccess}
              />
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    {COLUMNS.map(({ label, cls }) => (
                      <th
                        key={label}
                        className={`${cls} font-mono text-caption font-medium text-on-surface-variant uppercase tracking-[0.07em]`}
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
