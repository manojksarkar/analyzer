import { z } from 'zod'
import type { LocalFolders } from '../../types'

/* GET /repositories/local-folders: one folder's subfolders on the server ArtiFex runs on, for the
   New Project wizard's Local path "Browse…". Forward slashes; `path` '' is the top list. */

export const ApiLocalFoldersSchema = z.object({
  path: z.string(),
  parent: z.string().nullable().optional(),
  folders: z.array(z.object({ name: z.string(), path: z.string(), git: z.boolean() })),
  limited: z.boolean().optional(),
  truncated: z.boolean().optional(),
})
export type ApiLocalFolders = z.infer<typeof ApiLocalFoldersSchema>

export function mapLocalFolders(r: ApiLocalFolders): LocalFolders {
  return {
    path: r.path,
    parent: r.parent ?? null,
    folders: r.folders.map((f) => ({ name: f.name, path: f.path, git: f.git })),
    limited: !!r.limited,
    truncated: !!r.truncated,
  }
}
