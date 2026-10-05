import { z } from 'zod'
import type { AppNotification } from '../../types'
import { relativeTime } from '../../lib/format'

// A16: `document_id` names the document a review notification is about (null otherwise);
// `type` is `review_assigned`, `review_submitted`, … (REVIEW_APPROVE_API_SPEC A16).
export const ApiNotificationSchema = z.object({
  id: z.string(), project_id: z.string(), type: z.string(), message: z.string(),
  document_id: z.string().nullable(),
  read_at: z.string().nullable(), created_at: z.string(),
})
export type ApiNotification = z.infer<typeof ApiNotificationSchema>

export function mapNotification(n: ApiNotification): AppNotification {
  return {
    id: n.id,
    projectId: n.project_id,
    documentId: n.document_id ?? null,
    type: n.type,
    message: n.message,
    readAt: n.read_at,
    createdAt: n.created_at,
    relativeTime: relativeTime(n.created_at),
  }
}
