import { http } from '../../lib/http'

export interface RepoTestResult {
  connected: boolean
  defaultBranch: string | null
  branches: string[]
  message: string
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
    }>('/repositories/test-connection', body)
    return {
      connected: r.connected,
      defaultBranch: r.default_branch,
      branches: r.branches,
      message: r.message,
    }
  },
  /** Browse the source tree rooted at `path` (full nested subtree). */
  browse: async (
    repoUrl: string,
    ref?: string,
    path = '',
    accessToken?: string,
  ): Promise<RepoEntry[]> => {
    const r = await http.get<{ entries: RepoEntry[] }>('/repositories/browse', {
      repo_url: repoUrl,
      ref,
      path,
      access_token: accessToken,
    })
    return r.entries
  },
  upload: async (
    file: File,
    kind: 'preprocessor_definitions' | 'data_dictionary',
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
}
