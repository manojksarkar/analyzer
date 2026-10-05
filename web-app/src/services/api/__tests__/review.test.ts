import { describe, expect, it } from 'vitest'
import { http as mock, HttpResponse } from 'msw'
import { server } from '../../../test/server'
import { API_BASE_URL } from '../../../lib/http'
import { reviewApi } from '../review'

/* R1 was read with `limit: 1000` and no paging, so a version with more corrections than one page
   lost the rest: the page neither marked nor counted them. It is now read page by page until
   `total` (docs/spec/REVIEW_UPDATE_API_SPEC.md §6). */

const slot = (i: number) => ({
  slotKind: 'description', slotKey: `C|U|f${i}|int`, text: `t${i}`, llmText: 'old', humanText: `t${i}`,
  isOverridden: true, isOrphaned: false, canUndo: true, updatedBy: 'u1', updatedAt: null,
})

describe('reviewApi.overrides (R1)', () => {
  it('reads every page until total', async () => {
    const total = 2300
    const asked: { limit: string | null; offset: string | null }[] = []
    server.use(
      mock.get(`${API_BASE_URL}/projects/p1/versions/v1/overrides`, ({ request }) => {
        const q = new URL(request.url).searchParams
        asked.push({ limit: q.get('limit'), offset: q.get('offset') })
        const limit = Number(q.get('limit')), offset = Number(q.get('offset'))
        const rows = Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, i) => slot(offset + i))
        return HttpResponse.json({ overrides: rows, total, limit, offset })
      }),
    )
    const all = await reviewApi.overrides('p1', 'v1')
    expect(all).toHaveLength(total)
    expect(new Set(all.map((s) => s.key)).size).toBe(total)
    expect(asked).toEqual([
      { limit: '1000', offset: '0' }, { limit: '1000', offset: '1000' }, { limit: '1000', offset: '2000' },
    ])
  })

  it('one read when the first page holds them all', async () => {
    let calls = 0
    server.use(
      mock.get(`${API_BASE_URL}/projects/p1/versions/v1/overrides`, () => {
        calls += 1
        return HttpResponse.json({ overrides: [slot(0), slot(1)], total: 2, limit: 1000, offset: 0 })
      }),
    )
    expect(await reviewApi.overrides('p1', 'v1')).toHaveLength(2)
    expect(calls).toBe(1)
  })

  it('moves on by the page size: a page the server thinned (a row it could not show) neither ends the read nor overlaps the next', async () => {
    const asked: string[] = []
    server.use(
      mock.get(`${API_BASE_URL}/projects/p1/versions/v1/overrides`, ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'))
        asked.push(String(offset))
        // 2,000 corrections; the first page shows 998 of its 1,000, the third is past the end.
        const rows = offset === 0 ? Array.from({ length: 998 }, (_, i) => slot(i))
          : offset === 1000 ? Array.from({ length: 1000 }, (_, i) => slot(1000 + i)) : []
        return HttpResponse.json({ overrides: rows, total: 2000, limit: 1000, offset })
      }),
    )
    expect(await reviewApi.overrides('p1', 'v1')).toHaveLength(1998)
    expect(asked).toEqual(['0', '1000'])
  })

  it('an empty page short of total does not loop for ever: the read ends at total', async () => {
    let calls = 0
    server.use(
      mock.get(`${API_BASE_URL}/projects/p1/versions/v1/overrides`, () => {
        calls += 1
        return HttpResponse.json({ overrides: calls === 1 ? [slot(0)] : [], total: 1500, limit: 1000, offset: 0 })
      }),
    )
    expect(await reviewApi.overrides('p1', 'v1')).toHaveLength(1)
    expect(calls).toBe(2)
  })

  it('a row two pages return (a save shifted the rows between them) is listed once, by kind + key', async () => {
    server.use(
      mock.get(`${API_BASE_URL}/projects/p1/versions/v1/overrides`, ({ request }) => {
        const offset = Number(new URL(request.url).searchParams.get('offset'))
        const rows = offset === 0
          ? Array.from({ length: 1000 }, (_, i) => slot(i))
          : [slot(999), slot(1000)]
        return HttpResponse.json({ overrides: rows, total: 1002, limit: 1000, offset })
      }),
    )
    const all = await reviewApi.overrides('p1', 'v1')
    expect(all).toHaveLength(1001)
    expect(all.filter((s) => s.key === 'C|U|f999|int')).toHaveLength(1)
  })
})

describe('reviewApi.discardOrphans (R12)', () => {
  it('every orphan of the version, or one slot by kind and key', async () => {
    const seen: string[] = []
    server.use(
      mock.delete(`${API_BASE_URL}/projects/p1/versions/v1/overrides/orphans`, ({ request }) => {
        seen.push(new URL(request.url).search)
        return HttpResponse.json({ discarded: seen.length === 1 ? 3 : 1 })
      }),
    )
    expect(await reviewApi.discardOrphans('p1', 'v1')).toBe(3)
    expect(await reviewApi.discardOrphans('p1', 'v1', { kind: 'description', key: 'C|U|f|int' })).toBe(1)
    expect(seen[0]).toBe('')
    expect(new URLSearchParams(seen[1]).get('slot_kind')).toBe('description')
    expect(new URLSearchParams(seen[1]).get('slot_key')).toBe('C|U|f|int')
  })
})

describe('reviewApi.regenerationQueue (R10)', () => {
  it('reads the version’s queue', async () => {
    server.use(
      mock.get(`${API_BASE_URL}/projects/p1/versions/v1/regeneration-queue`, () => HttpResponse.json({
        pending: [{
          slotKind: 'unitDescription', slotKey: 'L2.Gpio|GpioDrv', reason: 'written from a corrected description',
          causedBy: { slotKind: 'description', slotKey: 'L2.Gpio|GpioDrv|Gpio_Init|void' }, requestedAt: null,
        }],
        total: 1,
      })),
    )
    const q = await reviewApi.regenerationQueue('p1', 'v1')
    expect(q).toHaveLength(1)
    expect(q[0].reason).toBe('written from a corrected description')
    expect(q[0].causedBy?.slotKind).toBe('description')
  })
})
