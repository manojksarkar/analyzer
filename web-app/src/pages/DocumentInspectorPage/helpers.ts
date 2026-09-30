/* Flowchart viewer math, kept pure so the zoom and pan rules are tested without a browser. */

/** Where the chart sits in the viewer: its top-left corner, in px of the viewer box, and scale. */
export interface ChartView {
  x: number
  y: number
  scale: number
}

export const MIN_SCALE = 0.05
export const MAX_SCALE = 4
/** Below this a flowchart's 12pt labels stop being readable. */
const READABLE_SCALE = 0.5
const PAD = 24

const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v))

/** The scale that shows the whole chart in the box -- never above 100%. */
export function fitScale(w: number, h: number, boxW: number, boxH: number): number {
  if (w <= 0 || h <= 0 || boxW <= 0 || boxH <= 0) return 1
  return clamp(Math.min((boxW - PAD * 2) / w, (boxH - PAD * 2) / h, 1), MIN_SCALE, 1)
}

/** The chart at `scale`, centred in the box. */
export function centred(w: number, h: number, boxW: number, boxH: number, scale: number): ChartView {
  return { scale, x: (boxW - w * scale) / 2, y: (boxH - h * scale) / 2 }
}

/** What the viewer opens on: the whole chart -- unless fitting it would shrink its text past
 *  reading, and then 100% at the top centre, where a flowchart starts. */
export function initialView(w: number, h: number, boxW: number, boxH: number): ChartView {
  const fit = fitScale(w, h, boxW, boxH)
  if (fit >= READABLE_SCALE) return centred(w, h, boxW, boxH, fit)
  return { scale: 1, x: (boxW - w) / 2, y: PAD }
}

/** Zoom by `factor`, keeping the point (px, py) of the box where it is on screen. */
export function zoomAt(v: ChartView, factor: number, px: number, py: number): ChartView {
  const scale = clamp(v.scale * factor, MIN_SCALE, MAX_SCALE)
  const k = scale / v.scale
  return { scale, x: px - (px - v.x) * k, y: py - (py - v.y) * k }
}
