import { useEffect, useRef, useState } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { UserRole } from '../../../types'

const ROLE_LABEL: Record<UserRole, string> = { admin: 'Admin', developer: 'Developer' }

/* ─── Role badge (read-only) ─── */
export function RolePill({ role }: { role: UserRole }) {
  const admin = role === 'admin'
  return (
    <span
      className={cn(
        'uppercase font-mono text-micro font-bold rounded-full tracking-[0.04em] whitespace-nowrap px-2 py-px',
        admin ? 'bg-surface-container text-secondary' : 'bg-muted text-on-surface-variant',
      )}
    >
      {admin ? 'Admin' : 'Dev'}
    </span>
  )
}

/* ─── Role dropdown (admin can change) ─── */
export function RoleSelect({ value, onChange, demoteLocked, label }: {
  value: UserRole
  onChange: (r: UserRole) => void
  /** Why Developer is not offered (the project's only admin), or null. */
  demoteLocked?: string | null
  /** The member's name, for the button's accessible name. */
  label?: string
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onDown(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])
  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={label ? `Role of ${label}: ${ROLE_LABEL[value]}` : undefined}
        className="inline-flex items-center gap-1 transition-colors hover:border-secondary hover:text-secondary px-2 py-[3px] border border-outline-variant rounded-md font-mono text-label font-semibold text-on-surface-variant bg-surface-container-lowest"
      >
        <span>{ROLE_LABEL[value]}</span>
        <Icon name="expand_more" size={11} />
      </button>
      {open && (
        <div role="menu" className="absolute left-0 bg-surface-container-lowest border border-outline-variant rounded-lg overflow-hidden top-[calc(100%+4px)] z-[200] shadow-[0_4px_20px_rgba(4,22,39,.12)] min-w-[150px]">
          {(['admin', 'developer'] as UserRole[]).map((r) => {
            const locked = r === 'developer' && value === 'admin' && demoteLocked ? demoteLocked : null
            return (
              <button
                key={r}
                role="menuitem"
                disabled={!!locked}
                title={locked ?? undefined}
                onClick={() => { onChange(r); setOpen(false) }}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-surface-container-low text-on-surface font-mono text-caption disabled:opacity-45 disabled:cursor-not-allowed disabled:hover:bg-surface-container-lowest"
              >
                <span>{ROLE_LABEL[r]}</span>
                {value === r && <Icon name="check" size={14} className="text-secondary" />}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
