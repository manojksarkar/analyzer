import { z } from 'zod'
import type { ConfigPreview, ConfigReportTopic, UploadedFile } from '../../types'

const ApiUploadedFileSchema = z.object({ file_id: z.string(), file_name: z.string(), size: z.number() })

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
    })),
    definitions: z.union([
      ApiUploadedFileSchema.extend({ mode: z.literal('upload') }),
      z.object({ mode: z.literal('manual'), defines: z.array(z.string()) }),
    ]).nullable(),
    data_dictionary: ApiUploadedFileSchema.nullable(),
    settings: z.record(z.string(), z.unknown()),
  }),
  expected_uploads: z.object({
    definitions: z.string().nullable(),
    data_dictionary: z.string().nullable(),
  }),
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

const TOPICS: ConfigReportTopic[] = ['project', 'architecture', 'files', 'settings', 'repository', 'other']
const topicOf = (t?: string): ConfigReportTopic =>
  TOPICS.includes(t as ConfigReportTopic) ? (t as ConfigReportTopic) : 'other'

export function mapConfigPreview(r: ApiConfigPreview): ConfigPreview {
  const d = r.draft
  return {
    draft: {
      name: d.name,
      repoUrl: d.repo_url,
      branch: d.branch,
      layers: d.architecture_layers.map((l) => ({
        name: l.name, path: l.path, libPaths: l.lib_paths, groups: l.groups,
      })),
      definitions: !d.definitions
        ? null
        : d.definitions.mode === 'upload'
          ? { kind: 'file', file: mapUploadedFile(d.definitions) }
          : { kind: 'typed', defines: d.definitions.defines },
      dataDictionary: d.data_dictionary ? mapUploadedFile(d.data_dictionary) : null,
      settings: d.settings,
    },
    expectedUploads: {
      definitions: r.expected_uploads.definitions,
      dataDictionary: r.expected_uploads.data_dictionary,
    },
    report: r.report.map((i) => ({ level: i.level, text: i.text, topic: topicOf(i.topic) })),
    repositoryChecked: r.repository_checked,
  }
}
