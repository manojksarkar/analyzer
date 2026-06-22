import { cn } from '../../lib/cn'

export type BadgeVariant = 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'mono'

const variants: Record<BadgeVariant, string> = {
  default:  'bg-surface-container text-on-surface-variant border border-outline-variant',
  primary:  'bg-secondary/10 text-secondary border border-secondary/20',
  success:  'bg-[#dcfce7] text-[#166534]',
  warning:  'bg-[#fef9c3] text-[#92400e]',
  danger:   'bg-[#fee2e2] text-[#991b1b]',
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
      className="inline-flex items-center rounded-full px-2 py-0.5 text-[9px] font-bold tracking-[0.1em]"
      style={{
        fontFamily: 'JetBrains Mono, monospace',
        background: role === 'admin' ? '#e5eeff' : '#f3f4f6',
        color: role === 'admin' ? '#0058be' : '#44474c',
      }}
    >
      {role === 'admin' ? 'ADMIN' : 'DEV'}
    </span>
  )
}

export function ProcessBadge({ process }: { process: string }) {
  return (
    <span className="inline-flex items-center rounded px-2 py-0.5 text-[10px] font-bold text-secondary bg-secondary/10">
      {process}
    </span>
  )
}
