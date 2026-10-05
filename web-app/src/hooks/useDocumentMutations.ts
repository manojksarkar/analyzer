import { useMutation } from '@tanstack/react-query'
import { documentsApi } from '../services/api'
import { toast } from '../components/ui/Toast'

/* Downloads. A document's review — assign, claim, submit, approve, request changes, reopen —
   is in hooks/useApproval.ts. */

/**
 * Returns a downloader for a document's DOCX (authed blob). Not a cache
 * mutation — just an action — so it stays a plain callback. A failure is
 * reported here: two of its three callers ignored the rejection, so a download
 * that failed (a missing DOCX, an expired session) did nothing visible.
 */
export function useDownloadDoc(projectId: string) {
  return async (docId: string, name: string): Promise<void> => {
    try {
      await documentsApi.download(projectId, docId, name)
    } catch (e) {
      toast.error('Download failed', `${name}: ${(e as Error).message}`)
    }
  }
}

/** Every DOCX of one version as a ZIP (`POST …/documents/export-all`, then its URL). */
export function useDownloadAll(projectId: string) {
  return useMutation({
    mutationFn: ({ versionId, fileName }: { versionId: string; fileName: string }) =>
      documentsApi.downloadAll(projectId, versionId, fileName),
    onError: (e: Error) => toast.error('Download failed', e.message),
  })
}
