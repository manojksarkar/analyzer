import { http } from '../../lib/http'
import type { LocalFolders } from '../../types'
import { ApiLocalFoldersSchema, mapLocalFolders } from '../mappers'

export interface RepoTestResult {
  connected: boolean
  defaultBranch: string | null
  branches: string[]
  message: string
  /** The URL the server connected to: a Bitbucket page address comes back as its clone URL.
   *  Absent from an older server. */
  repoUrl?: string
}

/** A node in the repository source tree (folders carry `children`). */
export interface RepoEntry {
  type: 'file' | 'folder'
  name: string
  path: string
  children?: RepoEntry[]
}

export interface RepoUpload {
  id: string
  fileName: string
  size: number
  kind: string
}

/** What a build-configuration upload is: a core's macros, data dictionary or compile commands. */
export type UploadKind = 'preprocessor_definitions' | 'data_dictionary' | 'compile_commands'

export const repositoriesApi = {
  testConnection: async (body: {
    repo_url: string
    repo_provider?: string
    access_token?: string
  }): Promise<RepoTestResult> => {
    const r = await http.post<{
      connected: boolean
      default_branch: string | null
      branches: string[]
      message: string
      repo_url?: string | null
    }>('/repositories/test-connection', body)
    return {
      connected: r.connected,
      defaultBranch: r.default_branch,
      branches: r.branches,
      message: r.message,
      ...(r.repo_url ? { repoUrl: r.repo_url } : {}),
    }
  },
  /** Browse the source tree rooted at `path` (full nested subtree). `refresh` fetches the
   *  branch's current tip first — the tree every path is checked against. A POST, so the access
   *  token travels in the body: in a URL it reached the server's access log, proxies and dev tools
   *  (the API refuses a GET that carries one). */
  browse: async (
    repoUrl: string,
    ref?: string,
    path = '',
    accessToken?: string,
    refresh = false,
  ): Promise<RepoEntry[]> => {
    const r = await http.post<{ entries: RepoEntry[] }>('/repositories/browse', {
      repo_url: repoUrl,
      ref: ref || undefined,
      path,
      access_token: accessToken || undefined,
      refresh,
    })
    return r.entries
  },
  upload: async (
    file: File,
    kind: UploadKind,
  ): Promise<RepoUpload> => {
    const form = new FormData()
    form.append('file', file)
    form.append('kind', kind)
    const r = await http.upload<{ id: string; file_name: string; size: number; kind: string }>(
      '/repositories/uploads',
      form,
    )
    return { id: r.id, fileName: r.file_name, size: r.size, kind: r.kind }
  },
  /** The subfolders of `path` on the server ArtiFex runs on, each marked when it is a git
   *  repository - for a Local path repository's Browse. '' (sent as no `path` at all) is the top
   *  list. 400 for a relative path, 403 outside the folders the server allows, 404 for no folder. */
  localFolders: async (path = ''): Promise<LocalFolders> =>
    mapLocalFolders(ApiLocalFoldersSchema.parse(
      await http.get('/repositories/local-folders', { path: path || undefined }))),
}
