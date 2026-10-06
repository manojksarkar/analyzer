import { cn } from '../../lib/cn'

export type BadgeVariant = 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'mono'

const variants: Record<BadgeVariant, string> = {
  default:  'bg-surface-container text-on-surface-variant border border-outline-variant',
  primary:  'bg-secondary/10 text-secondary border border-secondary/20',
  success:  'bg-state-done-bg text-success border border-success-line',
  warning:  'bg-state-warn-bg text-warn border border-amber',
  danger:   'bg-error-container text-on-error-container',
  mono:     'bg-surface-container border border-outline-variant text-on-surface-variant font-mono tracking-[0.06em]',
}

interface BadgeProps {
  variant?: BadgeVariant
  children: React.ReactNode
  className?: string
}

export function Badge({ variant = 'default', children, className }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold',
        variants[variant],
        className,
      )}
    >
      {children}
    </span>
  )
}

export function RoleBadge({ role }: { role: 'admin' | 'developer' }) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-[9px] font-bold tracking-[0.1em] font-mono',
        role === 'admin' ? 'bg-surface-container text-secondary' : 'bg-muted text-on-surface-variant',
      )}
    >
      {role === 'admin' ? 'ADMIN' : 'DEV'}
    </span>
  )
}

// Theme colours (index.css), so a badge follows the light or the dark theme.
const PROCESS_COLORS: Record<string, { bg: string; color: string }> = {
  'SWE.4': { bg: 'var(--hue-teal-bg)', color: 'var(--hue-teal-ink)' },
  'SWE.3': { bg: 'var(--color-surface-container)', color: 'var(--color-secondary)' },
  'SWE.2': { bg: 'var(--hue-indigo-bg)', color: 'var(--hue-indigo-ink)' },
  'SWE.1': { bg: 'var(--color-state-done-bg)', color: 'var(--color-success)' },
  'SYS.1': { bg: 'var(--color-violet-bg)', color: 'var(--color-violet)' },
  'SYS.2': { bg: 'var(--hue-orange-bg)', color: 'var(--hue-orange-ink)' },
}

export function ProcessBadge({ process }: { process: string }) {
  const { bg, color } = PROCESS_COLORS[process] ?? PROCESS_COLORS['SWE.3']
  return (
    <span
      // eslint-disable-next-line no-restricted-syntax -- the colour is the process's (data-driven)
      style={{
        fontFamily: "'JetBrains Mono'", fontSize: 10, fontWeight: 700,
        background: bg, color, padding: '2px 7px', borderRadius: 3,
        display: 'inline-flex', alignItems: 'center',
      }}
    >
      {process}
    </span>
  )
}
