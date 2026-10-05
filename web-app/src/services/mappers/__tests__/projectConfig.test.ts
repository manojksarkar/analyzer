import { describe, expect, it } from 'vitest'
import { ApiConfigPreviewSchema, mapConfigPreview, type ApiConfigPreview } from '../projectConfig'

const base: ApiConfigPreview = {
  draft: {
    name: 'Brake ECU',
    repo_url: 'https://example.invalid/brake.git',
    branch: 'dev',
    architecture_layers: [{
      name: 'Layer1', path: 'Layer1', lib_paths: [], core: 'Core1',
      groups: [{ name: 'My Sample', components: [{ name: 'Core', files: ['Layer1/Sample/Core'] }] }],
    }],
    cores: [{
      name: 'Core1',
      macros: { mode: 'upload', file_id: 'up_1', file_name: 'macros.json', size: 15 },
      data_dictionary: null,
      compile_commands: { file_id: 'up_2', file_name: 'compile_commands.json', size: 2 },
    }],
    settings: { views: { flowcharts: true } },
  },
  expected_uploads: { Core1: { macros: null, data_dictionary: 'dd.csv', compile_commands: null } },
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
    expect(p.repositoryChecked).toBe(true)
  })

  it('maps every core and the core each layer is built for', () => {
    const p = mapConfigPreview(base)
    expect(p.draft.layers[0].core).toBe('Core1')
    expect(p.draft.cores).toEqual([{
      name: 'Core1',
      macros: { kind: 'file', file: { fileId: 'up_1', fileName: 'macros.json', size: 15 } },
      dataDictionary: null,
      compileCommands: { fileId: 'up_2', fileName: 'compile_commands.json', size: 2 },
    }])
    expect(p.expectedUploads).toEqual({ Core1: { macros: null, dataDictionary: 'dd.csv', compileCommands: null } })
  })

  it('reads a layer with no core as null', () => {
    const layer = { ...base.draft.architecture_layers[0], core: undefined }
    const p = mapConfigPreview({ ...base, draft: { ...base.draft, architecture_layers: [layer] } })
    expect(p.draft.layers[0].core).toBeNull()
  })

  it('keeps what each report item is about, and reads an unknown or missing topic as other', () => {
    expect(mapConfigPreview(base).report[0].topic).toBe('architecture')
    const odd = mapConfigPreview({ ...base, report: [{ level: 'check', text: 'x', topic: 'nonsense' }, { level: 'check', text: 'y' }] })
    expect(odd.report.map((i) => i.topic)).toEqual(['other', 'other'])
  })

  it('maps typed macros from `project.defines`', () => {
    const core = { ...base.draft.cores[0], macros: { mode: 'manual' as const, defines: ['DEBUG=1'] } }
    const p = mapConfigPreview({ ...base, draft: { ...base.draft, cores: [core] } })
    expect(p.draft.cores[0].macros).toEqual({ kind: 'typed', defines: ['DEBUG=1'] })
  })
})
