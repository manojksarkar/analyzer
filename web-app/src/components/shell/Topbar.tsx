import { Link } from 'react-router-dom'
import { Icon } from '../ui'
import { NotificationBell } from './NotificationBell'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'

interface BreadcrumbItem {
  label: string
  to?: string
}

interface TopbarProps {
  breadcrumbs: BreadcrumbItem[]
}

export function Topbar({ breadcrumbs }: TopbarProps) {
  return (
    <header className="h-14 flex-shrink-0 flex items-center justify-between px-4 bg-surface-container-lowest border-b border-outline-variant z-30">
      {/* Breadcrumb */}
      <nav aria-label="Breadcrumb">
        <ol className="flex items-center gap-1.5">
          <li>
            <Link
              to="/projects"
              aria-label="Dashboard"
              className="w-7 h-7 flex items-center justify-center rounded-lg text-on-surface-variant hover:bg-surface-container transition-colors"
            >
              <Icon name="hexagon" size={18} fill />
            </Link>
          </li>
          {breadcrumbs.map((crumb, i) => (
            <li key={i} className="flex items-center gap-1.5">
              <span className="text-outline-variant select-none">/</span>
              {crumb.to ? (
                <Link
                  to={crumb.to}
                  className="text-on-surface-variant hover:text-on-surface transition-colors whitespace-nowrap font-mono text-xs font-medium"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  className="text-on-surface font-mono text-xs font-medium"
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
        <ThemeToggle />

        {/* Notifications */}
        <NotificationBell />

        <div className="w-px h-5 bg-outline-variant mx-1.5" aria-hidden />

        <UserMenu />
      </div>
    </header>
  )
}
