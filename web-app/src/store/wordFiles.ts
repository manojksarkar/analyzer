import { create } from 'zustand'

/* Word file updates, client side only (docs/design/WORD_FILE_UPDATES.md): which downloads wait
   for an update to end (a download's *Corrected file*: "The download starts when it is done."),
   and which components an update just wrote ("Word files updated · Download", for a little
   while). Not server data: R9 is React Query's. Not persisted: a reload forgets both. */

/** A download that waits for an update: one document's Word file (`docId`), or every Word file of
 *  a version as a zip (`versionId`, Download all's *Corrected files*). */
export interface PendingDownload {
  projectId: string
  fileName: string
  docId?: string
  versionId?: string
  /** A document's component(s): not downloaded when the update failed for them. */
  components?: string[]
}

/** How long "Word files updated · Download" stays after an update ends. */
export const JUST_UPDATED_MS = 20_000

interface WordFilesState {
  /** Downloads waiting for an update job to complete, by its job id. */
  pending: Record<string, PendingDownload[]>
  /** The components an update just wrote, per version id. */
  justUpdated: Record<string, string[]>
  addPending: (jobId: string, d: PendingDownload) => void
  /** Take (and forget) the downloads waiting for a job. */
  takePending: (jobId: string) => PendingDownload[]
  markUpdated: (versionId: string, components: string[]) => void
}

export const useWordFilesStore = create<WordFilesState>((set, get) => ({
  pending: {},
  justUpdated: {},
  addPending: (jobId, d) => set((s) => {
    const list = (s.pending[jobId] ?? []).filter((x) => x.docId !== d.docId || x.versionId !== d.versionId)
    return { pending: { ...s.pending, [jobId]: [...list, d] } }
  }),
  takePending: (jobId) => {
    const list = get().pending[jobId] ?? []
    if (list.length) {
      set((s) => {
        const next = { ...s.pending }
        delete next[jobId]
        return { pending: next }
      })
    }
    return list
  },
  markUpdated: (versionId, components) => {
    set((s) => ({ justUpdated: { ...s.justUpdated, [versionId]: components } }))
    setTimeout(() => set((s) => {
      if (s.justUpdated[versionId] !== components) return s
      const next = { ...s.justUpdated }
      delete next[versionId]
      return { justUpdated: next }
    }), JUST_UPDATED_MS)
  },
}))
