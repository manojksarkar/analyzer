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

/** The most documents the list route answers in one page (`per_page` ≤ 100, api/routes/documents.py). */
export const DOCUMENTS_PAGE_MAX = 100
/** A guard against an API that ignores `page`: never more than this many pages. */
const DOCUMENTS_MAX_PAGES = 100

interface DocumentsPage {
  documents: ApiDocument[]
  pagination?: { page?: number; per_page?: number; total?: number }
}

const getDocumentsPage = (projectId: string, filters: DocumentFilters) =>
  http.get<DocumentsPage>(`/projects/${projectId}/documents`, {
    version_id: filters.versionId,
    process: filters.process,
    status: filters.status,
    assignee_id: filters.assigneeId,
    q: filters.q,
    page: filters.page,
    per_page: filters.perPage,
  })

export const documentsApi = {
  /** One page of documents (the API's default page size is 20). */
  list: async (
    projectId: string,
    filters: DocumentFilters = {},
    versionTagById?: Record<string, string>,
  ): Promise<Document[]> => {
    const r = await getDocumentsPage(projectId, filters)
    return r.documents.map((d) => mapDocument(d, versionTagById))
  },
  /**
   * EVERY document that matches, page after page (`page` / `perPage` in `filters` are ignored).
   * A page holds at most 100, and a version of the office project has about 240 (3 layers ×
   * 40 components × SWE.3 and SWE.4): one page undercounted the lists, the KPIs, the version's
   * approval bar and bulk approve. The first page says the total; the rest are read together.
   */
  listAll: async (
    projectId: string,
    filters: DocumentFilters = {},
    versionTagById?: Record<string, string>,
  ): Promise<Document[]> => {
    const perPage = DOCUMENTS_PAGE_MAX
    const at = (page: number) => getDocumentsPage(projectId, { ...filters, page, perPage })
    const first = await at(1)
    const pages: ApiDocument[][] = [first.documents]
    const total = first.pagination?.total
    if (typeof total === 'number') {
      const count = Math.min(Math.ceil(total / perPage), DOCUMENTS_MAX_PAGES)
      const rest = await Promise.all(Array.from({ length: Math.max(count - 1, 0) }, (_, i) => at(i + 2)))
      pages.push(...rest.map((r) => r.documents))
    } else {
      // No total (an older API): read on until a short page — or one that adds nothing new.
      const seen = new Set(first.documents.map((d) => d.id))
      let last = first.documents
      for (let page = 2; last.length >= perPage && page <= DOCUMENTS_MAX_PAGES; page++) {
        last = (await at(page)).documents
        if (!last.some((d) => !seen.has(d.id))) break
        last.forEach((d) => seen.add(d.id))
        pages.push(last)
      }
    }
    // A document added while the pages were read can shift one onto two pages: keep it once.
    const byId = new Map<string, ApiDocument>()
    for (const d of pages.flat()) if (!byId.has(d.id)) byId.set(d.id, d)
    return [...byId.values()].map((d) => mapDocument(d, versionTagById))
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
