import { describe, expect, it } from 'vitest'
import { MAX_SCALE, MIN_SCALE, centred, fitScale, initialView, zoomAt } from '../helpers'

describe('fitScale', () => {
  it('shrinks a chart bigger than the box to fit, inside a margin', () => {
    expect(fitScale(2000, 1000, 1048, 548)).toBeCloseTo(0.5)
  })
  it('never enlarges a small chart past 100%', () => {
    expect(fitScale(200, 100, 1000, 800)).toBe(1)
  })
  it('is 1 for an unknown size', () => {
    expect(fitScale(0, 0, 1000, 800)).toBe(1)
  })
})

describe('initialView', () => {
  it('opens on the whole chart, centred, when it stays readable', () => {
    const v = initialView(2000, 1000, 1048, 548)
    expect(v).toEqual(centred(2000, 1000, 1048, 548, v.scale))
    expect(v.scale).toBeCloseTo(0.5)
  })
  it('opens a huge chart at 100% from the top centre instead of shrinking it past reading', () => {
    // A 500-box flowchart: ~10,700 x 37,300 px.
    expect(initialView(10700, 37300, 1200, 800)).toEqual({ scale: 1, x: (1200 - 10700) / 2, y: 24 })
  })
})

describe('zoomAt', () => {
  it('keeps the point under the cursor where it is', () => {
    const v = { x: 100, y: 50, scale: 1 }
    const z = zoomAt(v, 2, 300, 250)
    // The chart point under (300, 250) was (200, 200); at 2x it must still land on (300, 250).
    expect(z.scale).toBe(2)
    expect(z.x + 200 * z.scale).toBeCloseTo(300)
    expect(z.y + 200 * z.scale).toBeCloseTo(250)
  })
  it('stays within the zoom limits', () => {
    expect(zoomAt({ x: 0, y: 0, scale: 3 }, 10, 0, 0).scale).toBe(MAX_SCALE)
    expect(zoomAt({ x: 0, y: 0, scale: 0.1 }, 0.01, 0, 0).scale).toBe(MIN_SCALE)
  })
})
