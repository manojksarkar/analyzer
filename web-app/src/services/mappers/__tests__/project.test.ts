import { describe, expect, it } from 'vitest'
import { ApiProjectSchema, mapProject, type ApiProject } from '../project'

const base: ApiProject = {
  id: 'p1',
  name: 'Brake Control Unit',
  client: 'Acme Mobility',
  compliance_standard: 'ISO_26262',
  status: 'in_review',
  last_run_at: '2026-06-20T10:00:00Z',
  current_version: 'v1.2.0',
  doc_counts: { total: 12, approved: 5, in_review: 7 },
  team_count: 4,
  my_role: 'admin',
  repo_url: 'https://github.com/acme/bcu',
  default_branch: 'main',
  build_config: {},
  architecture_layers: [],
  created_at: '2026-06-01T00:00:00Z',
  updated_at: '2026-06-20T10:00:00Z',
}

describe('mapProject', () => {
  it('maps snake_case fields to the camelCase Project shape', () => {
    const p = mapProject(base)
    expect(p.id).toBe('p1')
    expect(p.repoPath).toBe(base.repo_url)
    expect(p.standard).toBe('ISO 26262')
    expect(p.userRole).toBe('admin')
  })

  it('computes approval progress from doc_counts', () => {
    expect(mapProject({ ...base, doc_counts: { total: 4, approved: 1 } }).progress).toBe(25)
  })

  it('maps the not_run status to the "never" page state', () => {
    expect(mapProject({ ...base, status: 'not_run' }).pageState).toBe('never')
  })

  it('survives empty doc_counts without throwing (progress = 0)', () => {
    expect(mapProject({ ...base, doc_counts: {} }).progress).toBe(0)
  })

  it('normalises both string-array and object architecture groups', () => {
    const p = mapProject({
      ...base,
      architecture_layers: [
        { name: 'L1', groups: ['G1', { name: 'G2', components: [{ name: 'C1', files: ['a.cpp'] }] }] },
      ],
    })
    expect(p.architectureLayers[0].groups[0]).toEqual({ name: 'G1', components: [] })
    expect(p.architectureLayers[0].groups[1].components[0]).toEqual({ name: 'C1', files: ['a.cpp'] })
  })

  it('the test DTO satisfies the contract schema (keeps the schema honest)', () => {
    expect(ApiProjectSchema.safeParse(base).success).toBe(true)
  })

  it('rejects a DTO whose required field has the wrong type', () => {
    const bad = { ...base, team_count: '4' }
    expect(ApiProjectSchema.safeParse(bad).success).toBe(false)
  })
})
