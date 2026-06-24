import { useState, useRef, useEffect } from 'react'
import {
  useNotifications, useMarkNotificationRead, useMarkAllNotificationsRead,
} from '../../hooks/useNotifications'
import { Icon } from '../ui'

/**
 * Notifications bell + dropdown, shared by the Topbar and the Projects header.
 * The API returns only unread notifications, so any item present is unread.
 */
export function NotificationBell() {
  const { data: notifications } = useNotifications()
  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onDown(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  const items = notifications ?? []
  const count = items.length

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative p-2 hover:bg-surface-container rounded-lg transition-colors"
        aria-label={`Notifications${count ? ` (${count} unread)` : ''}`}
        aria-haspopup="true"
        aria-expanded={open}
      >
        <Icon name="notifications" size={22} className="text-on-surface-variant" />
        {count > 0 && (
          <span className="absolute top-1.5 right-1.5 w-2 h-2 bg-error rounded-full border-2 border-white" aria-hidden />
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-1.5 bg-white border border-outline-variant rounded-xl overflow-hidden top-full z-[200] w-[340px] shadow-[0_4px_20px_rgba(4,22,39,.12)]">
          <div className="px-4 py-2.5 border-b border-outline-variant flex items-center justify-between">
            <span className="text-on-surface font-semibold text-body">Notifications</span>
            {count > 0 && (
              <button
                onClick={() => markAll.mutate()}
                className="text-secondary hover:underline font-mono text-caption"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-80 overflow-y-auto">
            {count === 0 ? (
              <p className="px-4 py-6 text-center text-on-surface-variant font-mono text-caption">
                You're all caught up.
              </p>
            ) : (
              items.map((n) => (
                <button
                  key={n.id}
                  onClick={() => markRead.mutate(n.id)}
                  className="w-full text-left px-4 py-3 border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors flex gap-3"
                >
                  <Icon name="circle_notifications" size={16} className="text-secondary flex-shrink-0 mt-0.5" />
                  <div className="flex-1 min-w-0">
                    <p className="text-on-surface text-xs leading-[1.4]">{n.message}</p>
                    <p className="text-on-surface-variant mt-0.5 font-mono text-label">{n.relativeTime}</p>
                  </div>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  )
}
