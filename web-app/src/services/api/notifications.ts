import { http } from '../../lib/http'
import type { AppNotification } from '../../types'
import { mapNotification, type ApiNotification } from '../mappers'

export const notificationsApi = {
  list: async (): Promise<AppNotification[]> => {
    const r = await http.get<{ notifications: ApiNotification[] }>('/notifications')
    return r.notifications.map(mapNotification)
  },
  markRead: (id: string): Promise<unknown> => http.patch(`/notifications/${id}/read`),
  markAllRead: (): Promise<unknown> => http.post('/notifications/read-all'),
}
