import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useProjects } from '../../hooks/useProjects'
import { Icon, TableSkeleton, toast } from '../../components/ui'
import { HomeTopbar } from '../../components/shell/HomeTopbar'
import { ProjectRow } from './components/ProjectRow'
import { ProjectsEmptyState } from './components/ProjectsEmptyState'
import { RenameProjectDialog } from './components/RenameProjectDialog'

/* Column headers — width baked into the class so no inline style is needed. */
const COLUMNS = [
  { label: 'Name',      cls: 'text-left px-5 py-3' },
  { label: 'Standard',  cls: 'text-left px-4 py-3' },
  { label: 'Latest',    cls: 'text-left px-4 py-3' },
  { label: 'In review', cls: 'text-right px-4 py-3' },
  { label: 'Progress',  cls: 'px-4 py-3 w-40' },
  { label: 'Last Run',  cls: 'text-left px-4 py-3' },
  { label: 'Team',      cls: 'text-left px-4 py-3' },
  { label: '',          cls: 'px-4 py-3 w-11' },
]

export function ProjectsPage() {
  const navigate = useNavigate()
  const { data: projects, isLoading, isError } = useProjects()
  const isEmpty = !isLoading && !isError && (projects?.length ?? 0) === 0
  const requestAccess = () =>
    toast.info('Request access', 'Ask your workspace administrator to add you to a project.')
  // The project being renamed (a row's menu). The dialog is the page's, not the row's: a click in
  // it would reach the row and open the project.
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null)

  return (
    <div className="h-screen flex flex-col overflow-hidden relative">
      {/* Dot grid background */}
      <div
        className="fixed inset-0 pointer-events-none -z-10 opacity-[0.025]"
        // eslint-disable-next-line no-restricted-syntax -- decorative dot-grid pattern (awkward as a utility)
        style={{ backgroundImage: 'radial-gradient(var(--color-inverse) 0.5px, transparent 0.5px)', backgroundSize: '24px 24px' }}
        aria-hidden
      />

      {/* ── Top bar ── */}
      <HomeTopbar />

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
                  className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-container-lowest border border-outline-variant hover:bg-surface-container-low text-on-surface rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em]"
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
          <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden mb-6">
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
                          onTeam={(id) => navigate(`/projects/${id}/team`)}
                          onRename={(p) => setRenaming({ id: p.id, name: p.name })}
                        />
                      ))}
                </tbody>
              </table>
            )}
            {isLoading && <TableSkeleton rows={5} cols={8} />}
          </div>
          {renaming && (
            <RenameProjectDialog
              project={renaming}
              otherNames={(projects ?? []).filter((p) => p.id !== renaming.id).map((p) => p.name)}
              onClose={() => setRenaming(null)}
            />
          )}
        </div>
      </div>
    </div>
  )
}
