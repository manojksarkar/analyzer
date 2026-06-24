import { http } from '../../lib/http'
import type { Project } from '../../types'
import { mapProject, type ApiProject } from '../mappers'

export interface CreateProjectInput {
  name: string
  client: string
  compliance_standard: string
  repo_url: string
  repo_provider?: string
  default_branch?: string
  access_token?: string
  build_config?: Record<string, unknown>
  architecture_layers?: unknown[]
  team?: { email: string; role: string }[]
}

export const projectsApi = {
  list: async (): Promise<Project[]> => {
    const r = await http.get<{ projects: ApiProject[] }>('/projects')
    return r.projects.map(mapProject)
  },
  get: async (id: string): Promise<Project> => {
    const r = await http.get<{ project: ApiProject }>(`/projects/${id}`)
    return mapProject(r.project)
  },
  create: async (body: CreateProjectInput): Promise<Project> => {
    const r = await http.post<{ project: ApiProject }>('/projects', body)
    return mapProject(r.project)
  },
  update: async (
    id: string,
    body: { name?: string; client?: string; status?: string },
  ): Promise<Project> => {
    const r = await http.patch<{ project: ApiProject }>(`/projects/${id}`, body)
    return mapProject(r.project)
  },
  remove: (id: string): Promise<void> => http.del(`/projects/${id}`),
  requestAccess: (id: string): Promise<unknown> =>
    http.post(`/projects/${id}/access-requests`),
  search: async (q: string): Promise<{ id: string; name: string; client: string }[]> => {
    const r = await http.get<{ projects: { id: string; name: string; client: string }[] }>(
      '/projects/search',
      { q },
    )
    return r.projects
  },
}
