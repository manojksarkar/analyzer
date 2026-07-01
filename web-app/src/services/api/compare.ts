import { http } from '../../lib/http'
import type { CompareResult, CompareDocumentDiff, CompareChangedDoc } from '../../types'
import { mapCompare, mapCompareDocumentDiff } from '../mappers'

export const compareApi = {
  summary: async (projectId: string, current: string, baseline: string): Promise<CompareResult> => {
    const r = await http.get<Parameters<typeof mapCompare>[0]>(`/projects/${projectId}/compare`, {
      current,
      baseline,
    })
    return mapCompare(r)
  },
  documents: async (
    projectId: string,
    current: string,
    baseline: string,
  ): Promise<{ documents: CompareChangedDoc[]; summary: CompareResult['summary'] }> => {
    const r = await http.get<{
      documents: { document_id: string; name: string; process: string; diff_type: string; sections_changed: string[] }[]
      summary: CompareResult['summary']
    }>(`/projects/${projectId}/compare/documents`, { current, baseline })
    return {
      documents: r.documents.map((d) => ({
        documentId: d.document_id,
        name: d.name,
        process: d.process,
        diffType: d.diff_type as CompareChangedDoc['diffType'],
        sectionsChanged: d.sections_changed,
      })),
      summary: r.summary,
    }
  },
  documentDetail: async (
    projectId: string,
    docId: string,
    current: string,
    baseline: string,
  ): Promise<CompareDocumentDiff> => {
    const r = await http.get<Parameters<typeof mapCompareDocumentDiff>[0]>(
      `/projects/${projectId}/compare/documents/${docId}`,
      { current, baseline },
    )
    return mapCompareDocumentDiff(r)
  },
}
