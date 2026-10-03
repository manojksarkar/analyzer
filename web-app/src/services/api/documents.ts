import { http } from '../../lib/http'
import type { Document, DocStats, DocumentDetail, RichDocument } from '../../types'
import {
  mapDocument, mapDocumentDetail, mapDocStats, mapRichDocument,
  type ApiDocument, type ApiDocumentDetail, type ApiRichDocument,
} from '../mappers'

export interface DocumentFilters {
  versionId?: string
  process?: string
  /** One of the four review states. */
  status?: string
  /** A user id, or `none` for the documents without a reviewer. */
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
  // A document's state moves only through the review and approval routes (approvalApi):
  // `PATCH …/{doc}` with a status and `PATCH …/sections/{key}` are retired.
  download: (projectId: string, docId: string, name: string): Promise<void> =>
    http.download(`/projects/${projectId}/documents/${docId}/download`, `${name}.docx`),
  exportAll: (
    projectId: string,
    body: { version_id: string; process_filter?: string[] },
  ): Promise<{ download_url: string }> =>
    http.post(`/projects/${projectId}/documents/export-all`, body),
  /** Every DOCX of a version as one ZIP: ask for the export, then fetch the URL it names. */
  downloadAll: async (projectId: string, versionId: string, fileName: string): Promise<void> => {
    const { download_url } = await documentsApi.exportAll(projectId, { version_id: versionId })
    // The URL is the API's own path (`/api/v1/projects/…`); the client adds its base itself.
    await http.download(download_url.replace(/^(?:https?:\/\/[^/]+)?\/api\/v\d+/, ''), fileName)
  },
}
