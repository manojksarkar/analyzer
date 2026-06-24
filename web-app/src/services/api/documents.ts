import { http } from '../../lib/http'
import type { Document, DocStats, DocumentDetail, RichDocument } from '../../types'
import {
  mapDocument, mapDocumentDetail, mapDocStats, mapRichDocument,
  type ApiDocument, type ApiDocumentDetail, type ApiRichDocument,
} from '../mappers'

export interface DocumentFilters {
  versionId?: string
  process?: string
  status?: string
  assigneeId?: string
  q?: string
  page?: number
  perPage?: number
}

export const documentsApi = {
  list: async (
    projectId: string,
    filters: DocumentFilters = {},
    versionTagById?: Record<string, string>,
  ): Promise<Document[]> => {
    const r = await http.get<{ documents: ApiDocument[] }>(`/projects/${projectId}/documents`, {
      version_id: filters.versionId,
      process: filters.process,
      status: filters.status,
      assignee_id: filters.assigneeId,
      q: filters.q,
      page: filters.page,
      per_page: filters.perPage,
    })
    return r.documents.map((d) => mapDocument(d, versionTagById))
  },
  stats: async (projectId: string, versionId?: string): Promise<DocStats> => {
    const r = await http.get<{ stats: Record<string, number> }>(
      `/projects/${projectId}/documents/stats`,
      { version_id: versionId },
    )
    return mapDocStats(r.stats)
  },
  get: async (
    projectId: string,
    docId: string,
    versionTagById?: Record<string, string>,
  ): Promise<DocumentDetail> => {
    const r = await http.get<{ document: ApiDocumentDetail }>(
      `/projects/${projectId}/documents/${docId}`,
    )
    return mapDocumentDetail(r.document, versionTagById)
  },
  render: async (projectId: string, docId: string): Promise<RichDocument> => {
    const r = await http.get<{ document: ApiRichDocument }>(
      `/projects/${projectId}/documents/${docId}/render`,
    )
    return mapRichDocument(r.document)
  },
  updateStatus: (projectId: string, docId: string, status: string): Promise<unknown> =>
    http.patch(`/projects/${projectId}/documents/${docId}`, { status }),
  approve: (projectId: string, docId: string): Promise<unknown> =>
    http.post(`/projects/${projectId}/documents/${docId}/approve`),
  requestChanges: (projectId: string, docId: string): Promise<unknown> =>
    http.post(`/projects/${projectId}/documents/${docId}/request-changes`),
  submitReview: (projectId: string, docId: string): Promise<unknown> =>
    http.post(`/projects/${projectId}/documents/${docId}/submit-review`),
  approveAll: (
    projectId: string,
    body: { version_id: string; process_filter?: string[] },
  ): Promise<{ approved_count: number }> =>
    http.post(`/projects/${projectId}/documents/approve-all`, body),
  assign: (projectId: string, docId: string, userIds: string[]): Promise<unknown> =>
    http.post(`/projects/${projectId}/documents/${docId}/assignments`, { user_ids: userIds }),
  removeAssignee: (projectId: string, docId: string, userId: string): Promise<void> =>
    http.del(`/projects/${projectId}/documents/${docId}/assignments/${userId}`),
  selfAssign: (projectId: string, docId: string): Promise<unknown> =>
    http.post(`/projects/${projectId}/documents/${docId}/assignments/self`),
  reviewSection: (
    projectId: string,
    docId: string,
    sectionKey: string,
    body: { review_state: string; edited_content?: string },
  ): Promise<unknown> =>
    http.patch(`/projects/${projectId}/documents/${docId}/sections/${sectionKey}`, body),
  download: (projectId: string, docId: string, name: string): Promise<void> =>
    http.download(`/projects/${projectId}/documents/${docId}/download`, `${name}.docx`),
  exportAll: (
    projectId: string,
    body: { version_id: string; process_filter?: string[] },
  ): Promise<{ download_url: string }> =>
    http.post(`/projects/${projectId}/documents/export-all`, body),
}
