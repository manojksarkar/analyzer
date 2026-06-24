import type { CompareResult, CompareDocumentDetail } from '../../types'

export function mapCompare(r: {
  current: CompareResult['current']
  baseline: CompareResult['baseline']
  summary: CompareResult['summary']
  changed_documents: { document_id: string; name: string; process: string; diff_type: string; sections_changed: string[] }[]
}): CompareResult {
  return {
    current: r.current,
    baseline: r.baseline,
    summary: r.summary,
    changedDocuments: (r.changed_documents ?? []).map((d) => ({
      documentId: d.document_id, name: d.name, process: d.process,
      diffType: d.diff_type as CompareResult['changedDocuments'][number]['diffType'],
      sectionsChanged: d.sections_changed,
    })),
  }
}

export function mapCompareDetail(r: {
  document_name: string
  sections: { key: string; title: string; diff_type: string; current_content: string; baseline_content: string }[]
}): CompareDocumentDetail {
  return {
    documentName: r.document_name,
    sections: (r.sections ?? []).map((s) => ({
      key: s.key, title: s.title,
      diffType: s.diff_type as CompareDocumentDetail['sections'][number]['diffType'],
      currentContent: s.current_content, baselineContent: s.baseline_content,
    })),
  }
}
