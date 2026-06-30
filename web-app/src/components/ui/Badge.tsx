import { cn } from '../../lib/cn'

export type BadgeVariant = 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'mono'

const variants: Record<BadgeVariant, string> = {
  default:  'bg-surface-container text-on-surface-variant border border-outline-variant',
  primary:  'bg-secondary/10 text-secondary border border-secondary/20',
  success:  'bg-[#f0fdf9] text-[#00a572] border border-[#86efac]',
  warning:  'bg-[#fff8e6] text-[#b45309] border border-[#f59e0b]',
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

const PROCESS_COLORS: Record<string, { bg: string; color: string }> = {
  'SWE.3': { bg: '#e5eeff', color: '#0058be' },
  'SWE.2': { bg: '#eef2ff', color: '#4f46e5' },
  'SWE.1': { bg: '#f0fdf9', color: '#00a572' },
  'SYS.1': { bg: '#faf5ff', color: '#7c3aed' },
  'SYS.2': { bg: '#fff7ed', color: '#c2410c' },
}

export function ProcessBadge({ process }: { process: string }) {
  const { bg, color } = PROCESS_COLORS[process] ?? { bg: '#e5eeff', color: '#0058be' }
  return (
    <span
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
