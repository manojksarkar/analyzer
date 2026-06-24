import { Icon } from '../../../components/ui'

/* ─── Empty state ───────────────────────────────────────────────────── */
export function ProjectsEmptyState({
  onNewProject,
  onRequestAccess,
}: {
  onNewProject: () => void
  onRequestAccess: () => void
}) {
  return (
    <div className="flex flex-col items-center justify-center text-center px-6 py-16">
      <div className="w-16 h-16 rounded-2xl bg-secondary-container flex items-center justify-center mb-6">
        <Icon name="folder_open" size={32} fill className="text-secondary" />
      </div>
      <h2 className="text-on-surface mb-2 text-lg font-semibold tracking-[-0.01em]">
        No projects yet
      </h2>
      <p className="text-on-surface-variant mb-8 text-body leading-[1.6] max-w-[440px]">
        Create a new project to start generating compliance documentation, or request access to an existing workspace.
      </p>

      {/* Choice cards */}
      <div className="grid grid-cols-2 gap-4 w-full max-w-[520px]">
        {/* New Project — leads to the create wizard */}
        <button
          onClick={onNewProject}
          className="group flex flex-col items-center gap-3 p-6 bg-white border-2 border-secondary rounded-xl hover:bg-secondary/5 transition-colors text-center"
        >
          <div className="w-10 h-10 rounded-xl bg-secondary flex items-center justify-center">
            <Icon name="add" size={20} className="text-white" />
          </div>
          <div>
            <p className="font-semibold text-on-surface mb-1 text-sm">New Project</p>
            <p className="text-on-surface-variant text-xs leading-[1.5]">
              Connect a C++ repository and generate your first compliance artifacts.
            </p>
          </div>
          <span className="mt-auto flex items-center gap-1 text-secondary text-xs font-semibold">
            Get started
            <Icon name="arrow_forward" size={14} />
          </span>
        </button>

        {/* Request Access — inline action (no navigation) */}
        <button
          onClick={onRequestAccess}
          className="group flex flex-col items-center gap-3 p-6 bg-white border border-outline-variant rounded-xl hover:bg-surface-container-low transition-colors text-center"
        >
          <div className="w-10 h-10 rounded-xl bg-surface-container flex items-center justify-center">
            <Icon name="lock" size={20} className="text-on-surface-variant" />
          </div>
          <div>
            <p className="font-semibold text-on-surface mb-1 text-sm">Request Access</p>
            <p className="text-on-surface-variant text-xs leading-[1.5]">
              Ask an admin to add you to an existing project workspace.
            </p>
          </div>
          <span className="mt-auto flex items-center gap-1 text-on-surface-variant text-xs font-semibold">
            Send request
            <Icon name="arrow_forward" size={14} />
          </span>
        </button>
      </div>
    </div>
  )
}
