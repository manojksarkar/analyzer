import { http } from '../../lib/http'
import type { AppNotification } from '../../types'
import { mapNotification, type ApiNotification } from '../mappers'

export const notificationsApi = {
  /** A16: the newest notifications, read ones included (`all=true`), newest first. */
  list: async (limit = 30): Promise<AppNotification[]> => {
    const r = await http.get<{ notifications: ApiNotification[] }>('/notifications', { all: true, limit })
    return r.notifications.map(mapNotification)
  },
  markRead: (id: string): Promise<unknown> => http.patch(`/notifications/${id}/read`),
  markAllRead: (): Promise<unknown> => http.post('/notifications/read-all'),
}
