import { z } from 'zod'
import type { ConfigPreview, ConfigReportTopic, CoreInputs, DraftCore, UploadedFile } from '../../types'

const ApiUploadedFileSchema = z.object({ file_id: z.string(), file_name: z.string(), size: z.number() })

const ApiDraftCoreSchema = z.object({
  name: z.string(),
  macros: z.union([
    ApiUploadedFileSchema.extend({ mode: z.literal('upload') }),
    z.object({ mode: z.literal('manual'), defines: z.array(z.string()) }),
  ]).nullable(),
  data_dictionary: ApiUploadedFileSchema.nullable(),
  compile_commands: ApiUploadedFileSchema.nullable(),
})

const ApiCoreInputsSchema = z.object({
  macros: z.string().nullable(),
  data_dictionary: z.string().nullable(),
  compile_commands: z.string().nullable(),
})

/** `POST /projects/config/preview` — a config file read into the New Project wizard. */
export const ApiConfigPreviewSchema = z.object({
  draft: z.object({
    name: z.string().nullable(),
    repo_url: z.string().nullable(),
    branch: z.string().nullable(),
    architecture_layers: z.array(z.object({
      name: z.string(),
      path: z.string(),
      lib_paths: z.array(z.string()),
      groups: z.array(z.object({
        name: z.string(),
        components: z.array(z.object({ name: z.string(), files: z.array(z.string()) })),
      })),
      core: z.string().nullable().optional(),
    })),
    cores: z.array(ApiDraftCoreSchema),
    settings: z.record(z.string(), z.unknown()),
  }),
  /** Per core: the path the config names for each of its files, as written. */
  expected_uploads: z.record(z.string(), ApiCoreInputsSchema),
  report: z.array(z.object({
    level: z.enum(['filled', 'check', 'skipped']),
    text: z.string(),
    topic: z.string().optional(),
  })),
  repository_checked: z.boolean(),
})
export type ApiConfigPreview = z.infer<typeof ApiConfigPreviewSchema>

const mapUploadedFile = (f: z.infer<typeof ApiUploadedFileSchema>): UploadedFile => ({
  fileId: f.file_id, fileName: f.file_name, size: f.size,
})

const mapDraftCore = (c: z.infer<typeof ApiDraftCoreSchema>): DraftCore => ({
  name: c.name,
  macros: !c.macros
    ? null
    : c.macros.mode === 'upload'
      ? { kind: 'file', file: mapUploadedFile(c.macros) }
      : { kind: 'typed', defines: c.macros.defines },
  dataDictionary: c.data_dictionary ? mapUploadedFile(c.data_dictionary) : null,
  compileCommands: c.compile_commands ? mapUploadedFile(c.compile_commands) : null,
})

const TOPICS: ConfigReportTopic[] = ['project', 'architecture', 'files', 'settings', 'repository', 'other']
const topicOf = (t?: string): ConfigReportTopic =>
  TOPICS.includes(t as ConfigReportTopic) ? (t as ConfigReportTopic) : 'other'

export function mapConfigPreview(r: ApiConfigPreview): ConfigPreview {
  const d = r.draft
  const expected: Record<string, CoreInputs<string | null>> = {}
  for (const [core, want] of Object.entries(r.expected_uploads)) {
    expected[core] = { macros: want.macros, dataDictionary: want.data_dictionary, compileCommands: want.compile_commands }
  }
  return {
    draft: {
      name: d.name,
      repoUrl: d.repo_url,
      branch: d.branch,
      layers: d.architecture_layers.map((l) => ({
        name: l.name, path: l.path, libPaths: l.lib_paths, groups: l.groups, core: l.core ?? null,
      })),
      cores: d.cores.map(mapDraftCore),
      settings: d.settings,
    },
    expectedUploads: expected,
    report: r.report.map((i) => ({ level: i.level, text: i.text, topic: topicOf(i.topic) })),
    repositoryChecked: r.repository_checked,
  }
}
