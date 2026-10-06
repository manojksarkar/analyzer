import { useNavigate } from 'react-router-dom'
import { Dropdown, DropdownTrigger, DropdownContent, Icon } from '../ui'
import { useAuthStore } from '../../store/auth'

/* The avatar and its menu, on every top bar. A superuser also gets Live logs (every project's runs
   and the API, /admin/logs); everyone gets Sign out. Profile is not built yet, so it is not offered
   (ui-review #36, #37). */
export function UserMenu() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const signOut = useAuthStore((s) => s.signOut)
  const items = [
    ...(user?.isSuperuser ? [{ label: 'Live logs', icon: 'terminal', onClick: () => navigate('/admin/logs') }] : []),
    { label: 'Sign out', icon: 'logout', variant: 'danger' as const, onClick: signOut },
  ]
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <button
          className="flex items-center gap-1.5 px-2 py-1.5 hover:bg-surface-container rounded-lg transition-colors"
          aria-label={`User menu — ${user?.name}`}
        >
          <div className="w-7 h-7 rounded-full bg-secondary-container flex items-center justify-center">
            {user?.initials
              ? <span className="text-on-secondary-container font-bold text-xs font-sans">{user.initials}</span>
              : <Icon name="person" size={16} className="text-on-secondary-container" />}
          </div>
          <Icon name="expand_more" size={16} className="text-on-surface-variant" />
        </button>
      </DropdownTrigger>
      <DropdownContent items={items} />
    </Dropdown>
  )
}
