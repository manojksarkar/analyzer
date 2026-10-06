import { http } from '../../lib/http'
import type { WordFileUpdateStart } from '../../types'
import { mapWordFileUpdateStart, type ApiWordFileUpdateStart } from '../mappers'

/* Word file updates (docs/design/WORD_FILE_UPDATES.md §4.1). The web app never says "re-export":
   the thing is the Word file, the action is Update. The route keeps its name. */

/** What to update: the out-of-date Word files (of `components`, when named), or every Word file
 *  of the version (`all`: an admin's Rebuild all). `documentId` is the document open: it widens a
 *  developer's reach by its component. */
export interface WordFileUpdateRequest {
  scope: 'out_of_date' | 'all'
  components?: string[]
  documentId?: string
}

export const wordFilesApi = {
  /** `POST V/reexport` (snake_case body). 202 started · 200 joined · 200 nothing out of date. */
  update: async (pid: string, vid: string, req: WordFileUpdateRequest): Promise<WordFileUpdateStart> =>
    mapWordFileUpdateStart(await http.post<ApiWordFileUpdateStart>(`/projects/${pid}/versions/${vid}/reexport`, {
      scope: req.scope,
      ...(req.components?.length ? { components: req.components } : {}),
      ...(req.documentId ? { document_id: req.documentId } : {}),
    })),
}
