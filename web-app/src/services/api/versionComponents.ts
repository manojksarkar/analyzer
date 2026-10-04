import { http } from '../../lib/http'
import type { ProjectRun, VersionComponents } from '../../types'
import { ApiProjectRunsSchema, ApiVersionComponentsSchema, mapProjectRuns, mapVersionComponents } from '../mappers'

/* Staged generation: a version's components and the documents still to make
   (api/routes/version_components.py — the same view as `analyzer.py components` / `export`). */

export interface GenerateResult {
  jobId: string
  components: string[]
  skipped: string[]
  /** Layers the job adds to the model first (parse + descriptions); empty when none. */
  addedLayers: string[]
}

export const versionComponentsApi = {
  list: async (pid: string, vid: string): Promise<VersionComponents> =>
    mapVersionComponents(ApiVersionComponentsSchema.parse(
      await http.get(`/projects/${pid}/versions/${vid}/components`))),
  /** The project's runs at work now, or cut short — a web job or `analyzer.py` on the server. */
  runs: async (pid: string): Promise<ProjectRun[]> =>
    mapProjectRuns(ApiProjectRunsSchema.parse(await http.get(`/projects/${pid}/runs`))),
  /** Make the documents of components the version has not generated yet (a job, Phases 3–4; 1–4
   *  when one is of a layer the model lacks: the job adds that layer first). */
  generate: async (pid: string, vid: string, components: string[]): Promise<GenerateResult> => {
    const r = await http.post<{ job_id: string; components: string[]; skipped: string[]; added_layers?: string[] }>(
      `/projects/${pid}/versions/${vid}/documents/generate`, { components })
    return {
      jobId: r.job_id, components: r.components ?? [], skipped: r.skipped ?? [], addedLayers: r.added_layers ?? [],
    }
  },
}
