import { describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL, ApiError, http as client } from '../../../lib/http'
import { mapExportReadiness, type ApiExportReadiness } from '../review'
import { mapSubmitWordFile, mapWordFileRefusal, mapWordFileUpdateStart } from '../wordFiles'

/* Word file updates on the wire (docs/design/WORD_FILE_UPDATES.md §4): R9 camelCase, the
   reexport answer, A5 and the errors snake_case. */

const R9: ApiExportReadiness = {
  stale: true,
  staleComponents: ['Layer1.Brake-Controller', 'Layer1.HVAC-Ctrl'],
  explanation: '2 Word file(s) are out of date', reason: 'a correction is newer than the Word file',
  overrideCount: 3, pendingRenders: 0, failedRenders: 0, oldestDerivationAt: null,
  outOfDate: [
    { documentId: 'docc1442', component: 'Layer1.Brake-Controller', name: 'Brake Controller', docType: 'SWE.3',
      why: ['corrections'], corrections: 2, pictures: 0, layer: null, updating: false },
    { documentId: 'docd7a10', component: 'Layer1.HVAC-Ctrl', name: 'HVAC Ctrl', docType: 'SWE.4',
      why: ['layerAdded', 'somethingNew'], corrections: 0, pictures: 0, layer: 'HAL_LAYER', updating: true },
  ],
  approvedKept: [
    { documentId: 'doce0b55', component: 'Layer1.HVAC-Ctrl', name: 'HVAC Ctrl', docType: 'SWE.3',
      why: ['layerAdded'], corrections: 0, pictures: 0, layer: 'HAL_LAYER' },
  ],
  writer: { kind: 'generation', jobId: 'job5e21aa0c', command: 'generate', since: '2026-10-05T08:00:00Z',
    components: null, componentsDone: 11, componentsTotal: 54, startedBy: null },
  reexport: { jobId: 'job3c9e1f20', status: 'running', startedAt: 'x', completedAt: null, errorMessage: null,
    scope: 'out_of_date', reason: 'update', components: ['Layer1.Brake-Controller'], componentsDone: 0,
    startedBy: { userId: 'u2', name: 'Developer B', initials: 'DB' } },
}

describe('R9 (camelCase)', () => {
  it('maps outOfDate, approvedKept, writer and the update’s new fields; drops a reason it does not know', () => {
    const r = mapExportReadiness(R9)
    expect(r.outOfDate?.[0]).toMatchObject({ documentId: 'docc1442', why: ['corrections'], corrections: 2, updating: false })
    expect(r.outOfDate?.[1]).toMatchObject({ why: ['layerAdded'], layer: 'HAL_LAYER', updating: true })
    expect(r.approvedKept?.[0]).toMatchObject({ documentId: 'doce0b55', updating: false })
    expect(r.writer).toMatchObject({ kind: 'generation', jobId: 'job5e21aa0c', componentsDone: 11, componentsTotal: 54 })
    expect(r.reexport).toMatchObject({
      scope: 'out_of_date', reason: 'update', components: ['Layer1.Brake-Controller'], componentsDone: 0,
      startedBy: { userId: 'u2', name: 'Developer B', initials: 'DB' },
    })
  })
  it('a partly failed update: componentsFailed comes through', () => {
    const r = mapExportReadiness({ ...R9, reexport: { ...R9.reexport!, status: 'complete',
      components: ['Layer1.Brake-Controller', 'Layer1.HVAC-Ctrl'], componentsFailed: ['Layer1.HVAC-Ctrl'] } })
    expect(r.reexport?.componentsFailed).toEqual(['Layer1.HVAC-Ctrl'])
  })
  it('an older API sends none of them: none are made up', () => {
    const old = { stale: false, explanation: null, overrideCount: 0, pendingRenders: 0, failedRenders: 0, reexport: null }
    const r = mapExportReadiness(old)
    expect(r).not.toHaveProperty('outOfDate')
    expect(r).not.toHaveProperty('writer')
  })
})

describe('the platform routes (snake_case)', () => {
  it('POST V/reexport: started, joined, or nothing out of date', () => {
    expect(mapWordFileUpdateStart({ job_id: 'job3c9e1f20', status: 'queued', version_id: 'verf6223ff0',
      scope: 'out_of_date', components: ['Layer1.Brake-Controller'], joined: false }))
      .toEqual({ jobId: 'job3c9e1f20', status: 'queued', versionId: 'verf6223ff0', scope: 'out_of_date',
        components: ['Layer1.Brake-Controller'], joined: false })
    expect(mapWordFileUpdateStart({ job_id: null, status: 'up_to_date', version_id: 'v', scope: 'out_of_date',
      components: [], joined: false })).toMatchObject({ jobId: null, status: 'up_to_date' })
  })
  it("A5's word_file: updating, or out of date with what held the version", () => {
    expect(mapSubmitWordFile({ state: 'updating', job_id: 'job3c9e1f20', blocked_by: null }))
      .toEqual({ state: 'updating', jobId: 'job3c9e1f20', blockedBy: null })
    expect(mapSubmitWordFile({ state: 'out_of_date', job_id: null, blocked_by: {
      kind: 'update', job_id: 'j9', command: 'reexport', since: null, components: ['Layer1.HVAC-Ctrl'],
      components_done: 0, components_total: 1, started_by: { user_id: 'u3', name: 'Dev C', initials: 'DC' },
      message: 'An update of HVAC Ctrl is running.',
    } })).toMatchObject({ state: 'out_of_date', blockedBy: {
      kind: 'update', jobId: 'j9', components: ['Layer1.HVAC-Ctrl'], startedBy: { userId: 'u3' },
      message: 'An update of HVAC Ctrl is running.',
    } })
    expect(mapSubmitWordFile(undefined)).toBeNull()
  })
  it("a refusal's extra fields", () => {
    expect(mapWordFileRefusal({ job_id: 'j1', scope: 'all', components: ['A', 'B'] }))
      .toMatchObject({ jobId: 'j1', kind: null, scope: 'all', components: ['A', 'B'], writer: null })
    // REEXPORT_RUNNING for a running resume: scope export, kind resume.
    expect(mapWordFileRefusal({ job_id: 'j2', kind: 'resume', scope: 'export', components: ['C'] }))
      .toMatchObject({ kind: 'resume', scope: 'export' })
    expect(mapWordFileRefusal({ writer: { kind: 'generation', job_id: 'j5', components: null } }).writer)
      .toMatchObject({ kind: 'generation', jobId: 'j5' })
    expect(mapWordFileRefusal({ why: ['corrections', 'layerAdded'], corrections: 2, layer: 'HAL_LAYER' }))
      .toMatchObject({ why: ['corrections', 'layerAdded'], corrections: 2, layer: 'HAL_LAYER' })
  })
})

describe('ApiError keeps an error’s other fields', () => {
  it('409 REEXPORT_RUNNING: its job, scope and components reach the page', async () => {
    server.use(http.post(`${API_BASE_URL}/x`, () => HttpResponse.json({ detail: {
      code: 'REEXPORT_RUNNING', message: 'An update is running.', status: 409,
      job_id: 'job1', scope: 'out_of_date', components: ['Layer1.Slip'],
    } }, { status: 409 })))
    const e = await client.post('/x').catch((x: unknown) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect((e as ApiError).code).toBe('REEXPORT_RUNNING')
    expect((e as ApiError).extra).toEqual({ job_id: 'job1', scope: 'out_of_date', components: ['Layer1.Slip'] })
  })
})
