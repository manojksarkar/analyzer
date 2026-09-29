import { http } from '../../lib/http'
import type { ConfigPreview, Project } from '../../types'
import { mapConfigPreview, mapProject, type ApiConfigPreview, type ApiProject } from '../mappers'

/** A config file to read into the New Project wizard; the repository when one is connected. */
export interface ConfigPreviewInput {
  text: string
  repo_url?: string
  branch?: string
  access_token?: string
}

/** One core of a new project, as the API stores it (api/services/project_cores.py). */
export interface CoreInput {
  name: string
  macros: { mode: 'upload'; file_id: string; file_name: string } | { mode: 'manual'; defines: string[] } | null
  data_dictionary: { file_id: string; file_name: string } | null
  compile_commands: { file_id: string; file_name: string } | null
}

export interface CreateProjectInput {
  name: string
  client: string
  compliance_standard: string
  repo_url: string
  repo_provider?: string
  default_branch?: string
  access_token?: string
  /** `cores`: each core's macros, data dictionary and compile commands (see CoreInput). */
  build_config?: Record<string, unknown>
  /** Each layer names its core: `{ ..., core: 'Core1' | null }`. */
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
  /** Fill the New Project wizard from a config file. Creates nothing. */
  previewConfig: async (body: ConfigPreviewInput): Promise<ConfigPreview> =>
    mapConfigPreview(await http.post<ApiConfigPreview>('/projects/config/preview', body)),
  /** The project as a config file — what `analyzer.py onboard --config` reads. */
  downloadConfig: (id: string, fileName: string): Promise<void> =>
    http.download(`/projects/${id}/config`, fileName),
}
