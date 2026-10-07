import { Link } from 'react-router-dom'
import { BrandMark } from '../ui'
import { NotificationBell } from './NotificationBell'
import { ThemeToggle } from './ThemeToggle'
import { UserMenu } from './UserMenu'
import { LogsButton } from '../livelogs/LogsButton'
import { APP_NAME, APP_TAGLINE } from '../../constants/branding'

/* The top bar of the pages outside a project (Projects): the brand, which leads to Projects,
   then the theme, Logs (superusers), the bell and the account menu. */
export function HomeTopbar() {
  return (
    <header className="h-14 flex-shrink-0 flex items-center justify-between px-6 bg-surface-container-lowest border-b border-outline-variant z-40">
      <Link to="/projects" className="flex items-center gap-3">
        <BrandMark size={32} className="flex-shrink-0 text-secondary" />
        <div>
          <h1 className="text-primary font-bold tracking-tight font-sans text-xl leading-[1.2]">
            {APP_NAME}
          </h1>
          <p className="text-on-surface-variant uppercase mt-0.5 font-mono text-caption font-medium tracking-[0.08em]">
            {APP_TAGLINE}
          </p>
        </div>
      </Link>
      <div className="flex items-center gap-0.5">
        <ThemeToggle />
        <LogsButton />
        <NotificationBell />
        <div className="w-px h-5 bg-outline-variant mx-1.5" aria-hidden />
        <UserMenu />
      </div>
    </header>
  )
}
