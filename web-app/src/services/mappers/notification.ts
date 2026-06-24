import type { AppNotification } from '../../types'
import { relativeTime } from '../../lib/format'

export interface ApiNotification {
  id: string; project_id: string; type: string; message: string
  read_at: string | null; created_at: string
}

export function mapNotification(n: ApiNotification): AppNotification {
  return {
    id: n.id,
    projectId: n.project_id,
    type: n.type,
    message: n.message,
    readAt: n.read_at,
    createdAt: n.created_at,
    relativeTime: relativeTime(n.created_at),
  }
}
