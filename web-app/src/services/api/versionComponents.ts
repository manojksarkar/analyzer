import { http } from '../../lib/http'
import type { VersionComponents } from '../../types'
import { ApiVersionComponentsSchema, mapVersionComponents } from '../mappers'

/* Staged generation: a version's components and the documents still to make
   (api/routes/version_components.py — the same view as `analyzer.py components` / `export`). */

export interface GenerateResult { jobId: string; components: string[]; skipped: string[] }

export const versionComponentsApi = {
  list: async (pid: string, vid: string): Promise<VersionComponents> =>
    mapVersionComponents(ApiVersionComponentsSchema.parse(
      await http.get(`/projects/${pid}/versions/${vid}/components`))),
  /** Make the documents of components the version has not generated yet (a job, Phases 3–4). */
  generate: async (pid: string, vid: string, components: string[]): Promise<GenerateResult> => {
    const r = await http.post<{ job_id: string; components: string[]; skipped: string[] }>(
      `/projects/${pid}/versions/${vid}/documents/generate`, { components })
    return { jobId: r.job_id, components: r.components ?? [], skipped: r.skipped ?? [] }
  },
}
