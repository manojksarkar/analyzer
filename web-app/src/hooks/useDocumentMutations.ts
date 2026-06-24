import { useMutation, useQueryClient } from '@tanstack/react-query'
import { documentsApi } from '../services/api'
import { toast } from '../components/ui/Toast'

/** Invalidate every documents query (any filter) + stats for a project. */
function useDocsInvalidate(projectId: string) {
  const qc = useQueryClient()
  return () =>
    qc.invalidateQueries({ queryKey: ['projects', projectId, 'documents'] })
}

export function useApproveDoc(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: (docId: string) => documentsApi.approve(projectId, docId),
    onSuccess: () => { invalidate(); toast.success('Document approved') },
    onError: (e: Error) => toast.error('Approve failed', e.message),
  })
}

/** Bulk-approve by looping the single-doc endpoint (no batch endpoint); one combined toast. */
export function useApproveDocs(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: (docIds: string[]) => Promise.all(docIds.map((id) => documentsApi.approve(projectId, id))),
    onSuccess: (_r, docIds) => {
      invalidate()
      toast.success(`Approved ${docIds.length} document${docIds.length !== 1 ? 's' : ''}`)
    },
    onError: (e: Error) => toast.error('Approve failed', e.message),
  })
}

/**
 * Returns a downloader for a document's DOCX (authed blob). Not a cache
 * mutation — just an action — so it stays a plain callback and the caller keeps
 * its own error handling (bulk download skips single failures silently).
 */
export function useDownloadDoc(projectId: string) {
  return (docId: string, name: string) => documentsApi.download(projectId, docId, name)
}

export function useRequestChanges(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: (docId: string) => documentsApi.requestChanges(projectId, docId),
    onSuccess: () => { invalidate(); toast.success('Changes requested') },
    onError: (e: Error) => toast.error('Request failed', e.message),
  })
}

export function useSubmitReview(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: (docId: string) => documentsApi.submitReview(projectId, docId),
    onSuccess: () => { invalidate(); toast.success('Submitted for review') },
    onError: (e: Error) => toast.error('Submit failed', e.message),
  })
}

export function useUpdateDocStatus(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: ({ docId, status }: { docId: string; status: string }) =>
      documentsApi.updateStatus(projectId, docId, status),
    onSuccess: () => { invalidate(); toast.success('Status updated') },
    onError: (e: Error) => toast.error('Update failed', e.message),
  })
}

export function useApproveAll(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: (body: { version_id: string; process_filter?: string[] }) =>
      documentsApi.approveAll(projectId, body),
    onSuccess: (r) => { invalidate(); toast.success(`Approved ${r.approved_count} document(s)`) },
    onError: (e: Error) => toast.error('Bulk approve failed', e.message),
  })
}

export function useAssignReviewers(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: ({ docId, userIds }: { docId: string; userIds: string[] }) =>
      documentsApi.assign(projectId, docId, userIds),
    onSuccess: () => { invalidate(); toast.success('Reviewers assigned') },
    onError: (e: Error) => toast.error('Assign failed', e.message),
  })
}

export function useSelfAssign(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: (docId: string) => documentsApi.selfAssign(projectId, docId),
    onSuccess: () => { invalidate(); toast.success('Claimed document') },
    onError: (e: Error) => toast.error('Could not claim', e.message),
  })
}

export function useReviewSection(projectId: string) {
  const invalidate = useDocsInvalidate(projectId)
  return useMutation({
    mutationFn: ({
      docId, sectionKey, reviewState, editedContent,
    }: { docId: string; sectionKey: string; reviewState: string; editedContent?: string }) =>
      documentsApi.reviewSection(projectId, docId, sectionKey, {
        review_state: reviewState,
        edited_content: editedContent,
      }),
    onSuccess: () => invalidate(),
    onError: (e: Error) => toast.error('Review failed', e.message),
  })
}
