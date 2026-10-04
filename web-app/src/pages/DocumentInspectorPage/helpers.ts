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

/** A flowchart's picture in the reading column: its own size, but no taller than `maxH`, so a
 *  tall chart (a long function is ~10,000 x 37,000 px) is drawn narrow rather than as a sliver
 *  letterboxed in a column-wide box; the column narrows a wide one (max-width 100%, the height
 *  following the ratio). Given as the image's width and height, it also reserves the space before
 *  the picture loads. Null when the size is not known (an older API). */
export function thumbSize(w: number | null | undefined, h: number | null | undefined, maxH = 480): { width: number; height: number } | null {
  if (!w || !h || w <= 0 || h <= 0) return null
  const k = Math.min(1, maxH / h)
  return { width: Math.max(1, Math.round(w * k)), height: Math.max(1, Math.round(h * k)) }
}

/** The viewer's keys: zoom (+ -), whole chart (0), move (arrows). */
export type ViewerKey = 'in' | 'out' | 'fit' | 'left' | 'right' | 'up' | 'down'
export function viewerKey(key: string): ViewerKey | null {
  switch (key) {
    case '+': case '=': return 'in'
    case '-': case '_': return 'out'
    case '0': return 'fit'
    case 'ArrowLeft': return 'left'
    case 'ArrowRight': return 'right'
    case 'ArrowUp': return 'up'
    case 'ArrowDown': return 'down'
    default: return null
  }
}
