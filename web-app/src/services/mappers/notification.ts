import { z } from 'zod'
import type { AppNotification } from '../../types'
import { relativeTime } from '../../lib/format'

export const ApiNotificationSchema = z.object({
  id: z.string(), project_id: z.string(), type: z.string(), message: z.string(),
  read_at: z.string().nullable(), created_at: z.string(),
})
export type ApiNotification = z.infer<typeof ApiNotificationSchema>

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
