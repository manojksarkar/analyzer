import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Icon, Modal, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { FlowchartEntry } from '../../../types'
import { type ChartView, centred, fitScale, initialView, zoomAt } from '../helpers'

/* One flowchart in a function's table: an SVG the engine draws on every run. A document can
   hold 500+, so each one loads only near the screen (native lazy loading), into space reserved
   from its known size so the page does not jump, and opens full screen to be read. */
export function FlowchartFigure({ chart }: { chart: FlowchartEntry }) {
  const [open, setOpen] = useState(false)

  if (chart.status === 'too_large') {
    return <FlowchartNote icon="account_tree" text={`Too large to draw (${chart.boxes} boxes)`} />
  }
  if (chart.status !== 'drawn' || !chart.imageUrl) {
    return <FlowchartNote icon="hide_image" text="Flowchart not drawn for this run" />
  }
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="Open full size"
        aria-label={`Open the flowchart of ${chart.label} full size`}
        className="group relative block max-w-full bg-white border border-outline-variant rounded-lg overflow-hidden hover:border-secondary focus-visible:border-secondary transition-colors"
      >
        <img
          src={chart.imageUrl}
          alt={`Flowchart of ${chart.label}`}
          loading="lazy"
          decoding="async"
          width={chart.width ?? undefined}
          height={chart.height ?? undefined}
          className="block max-w-full h-auto max-h-[480px] object-contain"
        />
        <span className="absolute top-1.5 right-1.5 flex items-center gap-1 px-1.5 py-0.5 rounded bg-white/90 border border-outline-variant text-on-surface-variant opacity-0 group-hover:opacity-100 group-focus-visible:opacity-100 transition-opacity">
          <Icon name="open_in_full" size={13} />
          <span className="font-mono text-label">Open</span>
        </span>
      </button>
      {open && <FlowchartViewer chart={chart} src={chart.imageUrl} onClose={() => setOpen(false)} />}
    </>
  )
}

function FlowchartNote({ icon, text }: { icon: string; text: string }) {
  return (
    <div className="inline-flex items-center gap-2 px-3 py-2.5 bg-surface-container-low border border-dashed border-outline-variant rounded-lg">
      <Icon name={icon} size={16} className="text-outline" />
      <Text variant="caption" className="font-mono">{text}</Text>
    </div>
  )
}

/* Full screen, zoom and pan. Opens on the whole chart, or at 100% from the top when the whole
   chart would be too small to read (a 500-box flowchart is ~10,000 x 37,000 px). The image is
   sized, not CSS-scaled, so the SVG is redrawn sharp at every zoom. */
function FlowchartViewer({ chart, src, onClose }: { chart: FlowchartEntry; src: string; onClose: () => void }) {
  const [boxEl, setBoxEl] = useState<HTMLDivElement | null>(null)
  const [box, setBox] = useState<{ w: number; h: number } | null>(null)
  const [loaded, setLoaded] = useState<{ w: number; h: number } | null>(null)
  const [moved, setMoved] = useState<ChartView | null>(null)
  const drag = useRef<{ x: number; y: number } | null>(null)

  // The API sends the size; an older API does not, and then the loaded image says it.
  const w = chart.width ?? loaded?.w ?? 0
  const h = chart.height ?? loaded?.h ?? 0
  const base = useMemo(() => (w && h && box ? initialView(w, h, box.w, box.h) : null), [w, h, box])
  const view = moved ?? base

  const move = useCallback(
    (f: (v: ChartView) => ChartView) => setMoved((m) => {
      const v = m ?? base
      return v ? f(v) : m
    }),
    [base],
  )

  useEffect(() => {
    if (!boxEl || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(([e]) => setBox({ w: e.contentRect.width, h: e.contentRect.height }))
    ro.observe(boxEl)
    return () => ro.disconnect()
  }, [boxEl])

  // Native, not onWheel: React's wheel listener is passive, and the page must not scroll too.
  useEffect(() => {
    if (!boxEl) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? boxEl.clientHeight : 1
      const r = boxEl.getBoundingClientRect()
      if (e.ctrlKey || e.metaKey) {
        move((v) => zoomAt(v, Math.exp(-e.deltaY * unit * 0.0015), e.clientX - r.left, e.clientY - r.top))
      } else {
        move((v) => ({ ...v, x: v.x - e.deltaX * unit, y: v.y - e.deltaY * unit }))
      }
    }
    boxEl.addEventListener('wheel', onWheel, { passive: false })
    return () => boxEl.removeEventListener('wheel', onWheel)
  }, [boxEl, move])

  const zoom = (factor: number) => box && move((v) => zoomAt(v, factor, box.w / 2, box.h / 2))
  const fit = () => box && w && h && setMoved(centred(w, h, box.w, box.h, fitScale(w, h, box.w, box.h)))
  const actual = () => box && move((v) => zoomAt(v, 1 / v.scale, box.w / 2, box.h / 2))

  return (
    <Modal
      open
      onClose={onClose}
      title={chart.label}
      description={chart.boxes ? `${chart.boxes} boxes` : undefined}
      className="max-w-none w-[calc(100vw-32px)] h-[calc(100vh-32px)] p-4 flex flex-col"
    >
      <div
        className="flex-1 min-h-0 flex flex-col gap-2 -mt-3"
        onKeyDown={(e) => {
          if (e.key === '+' || e.key === '=') zoom(1.25)
          else if (e.key === '-') zoom(0.8)
          else if (e.key === '0') fit()
        }}
      >
        <div className="flex items-center gap-1.5">
          <ToolButton icon="remove" label="Zoom out" onClick={() => zoom(0.8)} />
          <span className="w-12 text-center font-mono text-caption text-on-surface tabular-nums">
            {view ? `${Math.round(view.scale * 100)}%` : '…'}
          </span>
          <ToolButton icon="add" label="Zoom in" onClick={() => zoom(1.25)} />
          <ToolButton icon="fit_screen" label="Fit" text="Fit" onClick={fit} />
          <ToolButton icon="crop_free" label="Actual size" text="100%" onClick={actual} />
          <Text variant="caption" className="font-mono ml-auto hidden sm:block">
            Drag or scroll to move · Ctrl + scroll to zoom
          </Text>
        </div>
        <div
          ref={setBoxEl}
          className="relative flex-1 min-h-0 overflow-hidden rounded-xl bg-surface-container-low border border-outline-variant cursor-grab active:cursor-grabbing touch-none select-none"
          onPointerDown={(e) => {
            if (e.button !== 0) return
            drag.current = { x: e.clientX, y: e.clientY }
            e.currentTarget.setPointerCapture?.(e.pointerId)
          }}
          onPointerMove={(e) => {
            const d = drag.current
            if (!d) return
            drag.current = { x: e.clientX, y: e.clientY }
            move((v) => ({ ...v, x: v.x + e.clientX - d.x, y: v.y + e.clientY - d.y }))
          }}
          onPointerUp={() => { drag.current = null }}
          onPointerCancel={() => { drag.current = null }}
        >
          <img
            src={src}
            alt={`Flowchart of ${chart.label}`}
            draggable={false}
            onLoad={(e) => {
              if (!chart.width || !chart.height) {
                setLoaded({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })
              }
            }}
            className={cn('absolute left-0 top-0 max-w-none bg-white shadow-[0_1px_4px_rgba(4,22,39,.08)]', !view && 'invisible')}
            // eslint-disable-next-line no-restricted-syntax -- position and size follow the reader's zoom and pan
            style={view && w && h ? { transform: `translate(${view.x}px, ${view.y}px)`, width: w * view.scale, height: h * view.scale } : undefined}
          />
        </div>
      </div>
    </Modal>
  )
}

function ToolButton({ icon, label, text, onClick }: { icon: string; label: string; text?: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className="flex items-center gap-1 px-2 py-1 border border-outline-variant rounded-lg hover:border-secondary hover:text-secondary text-on-surface-variant transition-colors"
    >
      <Icon name={icon} size={15} />
      {text && <span className="font-mono text-label">{text}</span>}
    </button>
  )
}
