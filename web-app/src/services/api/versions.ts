import { http } from '../../lib/http'
import type { Version } from '../../types'
import { mapVersion, type ApiVersion } from '../mappers'

export const versionsApi = {
  list: async (projectId: string): Promise<Version[]> => {
    const r = await http.get<{ versions: ApiVersion[] }>(`/projects/${projectId}/versions`)
    return r.versions.map(mapVersion)
  },
  get: async (projectId: string, versionId: string): Promise<Version> => {
    const r = await http.get<{ version: ApiVersion }>(
      `/projects/${projectId}/versions/${versionId}`,
    )
    return mapVersion(r.version)
  },
  create: async (
    projectId: string,
    body: { tag: string; commit_sha: string; branch?: string; description?: string },
  ): Promise<Version> => {
    const r = await http.post<{ version: ApiVersion }>(`/projects/${projectId}/versions`, body)
    return mapVersion(r.version)
  },
  update: async (
    projectId: string,
    versionId: string,
    body: { status?: string; description?: string },
  ): Promise<Version> => {
    const r = await http.patch<{ version: ApiVersion }>(
      `/projects/${projectId}/versions/${versionId}`,
      body,
    )
    return mapVersion(r.version)
  },
  remove: (projectId: string, versionId: string): Promise<void> =>
    http.del(`/projects/${projectId}/versions/${versionId}`),
}
