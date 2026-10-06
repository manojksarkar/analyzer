import { useThemeStore } from '../../store/theme'
import { cn } from '../../lib/cn'
import { Icon } from '../ui'

/**
 * Sun / moon: switches between the dark and the light theme. In a header it is the first of the
 * right-hand actions (docs/ui-mockups/theme-toggle.js); a page without a header (sign-in) passes
 * `floating` and it sits in the top-right corner.
 */
export function ThemeToggle({ floating = false }: { floating?: boolean }) {
  const theme = useThemeStore((s) => s.theme)
  const toggleTheme = useThemeStore((s) => s.toggleTheme)
  const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
  return (
    <button
      type="button"
      onClick={toggleTheme}
      title={label}
      aria-label={label}
      className={cn(
        'transition-colors',
        floating
          ? 'fixed top-4 right-4 z-[200] flex p-2 rounded-full border border-outline-variant bg-surface-container-lowest hover:bg-surface-container'
          : 'relative p-2 hover:bg-surface-container rounded-lg',
      )}
    >
      <Icon name={theme === 'dark' ? 'light_mode' : 'dark_mode'} size={22} className="text-on-surface-variant" />
    </button>
  )
}
