import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  useNotifications, useMarkNotificationRead, useMarkAllNotificationsRead,
} from '../../hooks/useNotifications'
import { Icon } from '../ui'
import { cn } from '../../lib/cn'
import type { AppNotification } from '../../types'

/* A review notification's icon and colour (REVIEW_APPROVE_API_SPEC A16 `type`). */
const TYPE_ICON: Record<string, { icon: string; cls: string }> = {
  review_assigned:          { icon: 'person_add',      cls: 'text-[#7c3aed]' },
  review_unassigned:        { icon: 'person_remove',   cls: 'text-[#7c3aed]' },
  review_claimed:           { icon: 'front_hand',      cls: 'text-[#7c3aed]' },
  review_submitted:         { icon: 'pending_actions', cls: 'text-secondary' },
  review_approved:          { icon: 'check_circle',    cls: 'text-[#00a572]' },
  review_changes_requested: { icon: 'undo',            cls: 'text-error' },
  review_reopened:          { icon: 'lock_open',       cls: 'text-[#b45309]' },
  review_back_in_review:    { icon: 'rate_review',     cls: 'text-[#b45309]' },
}
const OTHER = { icon: 'circle_notifications', cls: 'text-secondary' }

/**
 * Notifications bell + dropdown, shared by the Topbar and the Projects header. Read ones are
 * listed too (greyed); the count is of the unread. A click marks one read and opens its document.
 */
export function NotificationBell() {
  const { data: notifications } = useNotifications()
  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllNotificationsRead()
  const navigate = useNavigate()
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
  const unread = items.filter((n) => !n.readAt).length

  function openItem(n: AppNotification) {
    if (!n.readAt) markRead.mutate(n.id)
    if (n.documentId) {
      setOpen(false)
      // A review notification opens the document on its Review tab: what happened, and what next.
      navigate(`/projects/${n.projectId}/documents/${n.documentId}?tab=review`)
    }
  }

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="relative p-2 hover:bg-surface-container rounded-lg transition-colors"
        aria-label={`Notifications${unread ? ` (${unread} unread)` : ''}`}
        aria-haspopup="true"
        aria-expanded={open}
      >
        <Icon name="notifications" size={22} className="text-on-surface-variant" />
        {unread > 0 && (
          <span className="absolute top-0.5 right-0 min-w-4 h-4 px-1 rounded-full bg-error text-white border-2 border-white box-content font-sans text-micro font-bold leading-4 text-center" aria-hidden>
            {unread > 9 ? '9+' : unread}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 mt-1.5 bg-white border border-outline-variant rounded-xl overflow-hidden top-full z-[200] w-[340px] shadow-[0_4px_20px_rgba(4,22,39,.12)]">
          <div className="px-4 py-2.5 border-b border-outline-variant flex items-center justify-between">
            <span className="text-on-surface font-semibold text-body">Notifications</span>
            {unread > 0 && (
              <button
                onClick={() => markAll.mutate()}
                className="text-secondary hover:underline font-mono text-caption"
              >
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <p className="px-4 py-6 text-center text-on-surface-variant font-mono text-caption">
                Nothing new.
              </p>
            ) : (
              items.map((n) => {
                const isUnread = !n.readAt
                const t = TYPE_ICON[n.type] ?? OTHER
                return (
                  <button
                    key={n.id}
                    onClick={() => openItem(n)}
                    title={n.documentId ? 'Open the document' : undefined}
                    className={cn(
                      'w-full text-left px-4 py-3 border-b border-outline-variant last:border-0 hover:bg-surface-container-low transition-colors flex gap-3',
                      isUnread ? 'bg-[#f5f8ff]' : 'bg-white',
                    )}
                  >
                    <Icon name={t.icon} size={16} fill className={cn('flex-shrink-0 mt-0.5', isUnread ? t.cls : 'text-outline')} />
                    <div className="flex-1 min-w-0">
                      <p className={cn('text-xs leading-[1.4]', isUnread ? 'text-on-surface' : 'text-outline')}>{n.message}</p>
                      <p className="text-outline mt-0.5 font-mono text-label">{n.relativeTime}</p>
                    </div>
                    {isUnread && <span className="w-[7px] h-[7px] rounded-full bg-secondary flex-shrink-0 mt-1.5" aria-label="Unread" />}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}
    </div>
  )
}
