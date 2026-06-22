import { Link } from 'react-router-dom'
import { useAuthStore } from '../../store/auth'
import { Dropdown, DropdownTrigger, DropdownContent } from '../ui'

interface BreadcrumbItem {
  label: string
  to?: string
}

interface TopbarProps {
  breadcrumbs: BreadcrumbItem[]
}

export function Topbar({ breadcrumbs }: TopbarProps) {
  const { user, signOut } = useAuthStore()

  return (
    <header className="h-14 flex-shrink-0 flex items-center justify-between px-4 bg-white border-b border-outline-variant z-30">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb">
        <ol className="flex items-center gap-1.5">
          <li>
            <Link
              to="/projects"
              aria-label="Dashboard"
              className="w-7 h-7 flex items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container transition-colors"
            >
              <span className="material-symbols-outlined sym-fill" style={{ fontSize: 18 }} aria-hidden>hexagon</span>
            </Link>
          </li>
          {breadcrumbs.map((crumb, i) => (
            <li key={i} className="flex items-center gap-1.5">
              <span className="text-outline-variant select-none">/</span>
              {crumb.to ? (
                <Link
                  to={crumb.to}
                  className="text-on-surface-variant hover:text-on-surface transition-colors"
                  style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  className="text-on-surface"
                  style={{ fontFamily: "'JetBrains Mono'", fontSize: 12, fontWeight: 500 }}
                  aria-current="page"
                >
                  {crumb.label}
                </span>
              )}
            </li>
          ))}
        </ol>
      </nav>

      {/* Right actions */}
      <div className="flex items-center gap-0.5">
        {/* Notifications */}
        <button
          className="relative p-2 hover:bg-surface-container rounded-lg transition-colors"
          aria-label="Notifications"
        >
          <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 22 }} aria-hidden>notifications</span>
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-error rounded-full border-2 border-white" aria-hidden />
        </button>

        {/* Help */}
        <button
          className="p-2 hover:bg-surface-container rounded-lg transition-colors"
          aria-label="Help"
        >
          <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 22 }} aria-hidden>help</span>
        </button>

        <div className="w-px h-5 bg-outline-variant mx-1.5" aria-hidden />

        {/* User avatar + dropdown */}
        <Dropdown>
          <DropdownTrigger asChild>
            <button
              className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-container rounded-lg transition-colors"
              aria-label={`User menu — ${user?.name}`}
            >
              <div className="w-7 h-7 rounded-full bg-secondary-container flex items-center justify-center">
                <span
                  className="text-on-secondary-container font-bold text-xs"
                  style={{ fontFamily: 'Inter' }}
                >
                  {user?.initials ?? 'EL'}
                </span>
              </div>
              <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 16 }} aria-hidden>expand_more</span>
            </button>
          </DropdownTrigger>
          <DropdownContent
            items={[
              { label: 'Profile',   icon: 'person', onClick: () => {} },
              { label: 'Sign out',  icon: 'logout', variant: 'danger', onClick: signOut },
            ]}
          />
        </Dropdown>
      </div>
    </header>
  )
}
