import { describe, expect, it } from 'vitest'
import { ApiConfigPreviewSchema, mapConfigPreview, type ApiConfigPreview } from '../projectConfig'

const base: ApiConfigPreview = {
  draft: {
    name: 'Brake ECU',
    repo_url: 'https://example.invalid/brake.git',
    branch: 'dev',
    architecture_layers: [{
      name: 'Layer1', path: 'Layer1', lib_paths: [],
      groups: [{ name: 'My Sample', components: [{ name: 'Core', files: ['Layer1/Sample/Core'] }] }],
    }],
    definitions: { mode: 'upload', file_id: 'up_1', file_name: 'macros.json', size: 15 },
    data_dictionary: null,
    settings: { views: { flowcharts: true } },
  },
  expected_uploads: { definitions: null, data_dictionary: 'dd.csv' },
  report: [{ level: 'filled', text: 'Architecture: 1 layer.', topic: 'architecture' }],
  repository_checked: true,
}

describe('mapConfigPreview', () => {
  it('matches the schema the API is checked against', () => {
    expect(ApiConfigPreviewSchema.safeParse(base).success).toBe(true)
  })

  it('maps the draft the wizard fills itself from', () => {
    const p = mapConfigPreview(base)
    expect(p.draft.repoUrl).toBe('https://example.invalid/brake.git')
    expect(p.draft.layers[0].libPaths).toEqual([])
    expect(p.draft.layers[0].groups[0].components[0].files).toEqual(['Layer1/Sample/Core'])
    expect(p.draft.definitions).toEqual({ kind: 'file', file: { fileId: 'up_1', fileName: 'macros.json', size: 15 } })
    expect(p.expectedUploads).toEqual({ definitions: null, dataDictionary: 'dd.csv' })
    expect(p.repositoryChecked).toBe(true)
  })

  it('keeps what each report item is about, and reads an unknown or missing topic as other', () => {
    expect(mapConfigPreview(base).report[0].topic).toBe('architecture')
    const odd = mapConfigPreview({ ...base, report: [{ level: 'check', text: 'x', topic: 'nonsense' }, { level: 'check', text: 'y' }] })
    expect(odd.report.map((i) => i.topic)).toEqual(['other', 'other'])
  })

  it('maps typed definitions from `project.defines`', () => {
    const p = mapConfigPreview({ ...base, draft: { ...base.draft, definitions: { mode: 'manual', defines: ['DEBUG=1'] } } })
    expect(p.draft.definitions).toEqual({ kind: 'typed', defines: ['DEBUG=1'] })
  })
})
