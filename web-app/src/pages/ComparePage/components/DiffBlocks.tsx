import { useState } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { parseSectionBody } from '../../../lib/markdown'
import type { CompareBlock, DiffMark, DiffSegment } from '../../../types'

/* ─── Inline highlight styling by change mark ─── */
const MARK_INLINE: Record<DiffMark, string> = {
  none:   '',
  add:    'bg-[rgba(0,165,114,.18)] text-on-tertiary-container rounded-[2px] px-px',
  del:    'bg-error-container text-error line-through rounded-[2px] px-px',
  change: 'bg-[#fff1cc] text-[#92600a] rounded-[2px] px-px',
}
const MARK_CELL: Record<DiffMark, string> = {
  none:   '',
  add:    'bg-[rgba(0,165,114,.14)]',
  del:    'bg-error-container/70 line-through',
  change: 'bg-[#fff4d6]',
}

/* ─── Inline word-level highlighted text ─── */
function Segments({ segments }: { segments: DiffSegment[] }) {
  if (!segments.length) return null
  return (
    <>
      {segments.map((s, i) =>
        s.mark === 'none'
          ? <span key={i}>{s.text}</span>
          : <span key={i} className={MARK_INLINE[s.mark]}>{s.text}</span>,
      )}
    </>
  )
}

/* ─── Mermaid / diagram block with a "changed" badge + source toggle ─── */
function DiffDiagramBlock({ block }: { block: Extract<CompareBlock, { kind: 'diagram' }> }) {
  const [showSrc, setShowSrc] = useState(false)
  return (
    <figure className={cn(
      'bg-surface-container-low border rounded-lg overflow-hidden',
      block.changed ? 'border-secondary/60' : 'border-outline-variant',
    )}>
      {block.imageUrl ? (
        <img src={block.imageUrl} alt={block.caption ?? 'Diagram'} loading="lazy"
             className="block w-full max-h-[400px] object-contain bg-white" />
      ) : (
        <div className="flex flex-col items-center justify-center text-center py-10 gap-2">
          <Icon name="account_tree" size={32} className="text-outline-variant" />
          <span className="font-mono text-caption text-on-surface-variant">{block.caption ?? 'Diagram'}</span>
        </div>
      )}
      <figcaption className="flex items-center justify-between gap-2 px-3 py-2 border-t border-outline-variant bg-white">
        <span className="flex items-center gap-1.5 font-mono text-label text-on-surface-variant truncate">
          {block.changed && <span className="px-1.5 py-0.5 rounded bg-secondary/10 text-secondary font-semibold">diagram changed</span>}
          <span className="truncate">{block.caption ?? 'Diagram'}</span>
        </span>
        {block.mermaid && (
          <button onClick={() => setShowSrc((v) => !v)}
                  className="flex items-center gap-1 flex-shrink-0 text-secondary hover:underline font-mono text-label">
            <Icon name="code" size={12} />{showSrc ? 'Hide source' : 'View source'}
          </button>
        )}
      </figcaption>
      {showSrc && block.mermaid && (
        <pre className="px-3 py-2 bg-surface-container-low border-t border-outline-variant overflow-x-auto font-mono text-label text-on-surface-variant whitespace-pre">{block.mermaid}</pre>
      )}
    </figure>
  )
}

/* ─── One diff block (text | keyvalue | table | diagram) ─── */
function DiffBlockView({ block }: { block: CompareBlock }) {
  if (block.kind === 'text') {
    return (
      <p className="text-sm text-on-surface leading-relaxed whitespace-pre-line">
        <Segments segments={block.segments} />
      </p>
    )
  }
  if (block.kind === 'keyvalue') {
    return (
      <div className="flex items-baseline gap-2 text-sm">
        <span className="font-mono text-caption text-on-surface-variant flex-shrink-0">{block.label}:</span>
        <span className="text-on-surface"><Segments segments={block.segments} /></span>
      </div>
    )
  }
  if (block.kind === 'diagram') {
    return <DiffDiagramBlock block={block} />
  }
  // table
  return (
    <div className="overflow-x-auto border border-outline-variant rounded-lg">
      <table className="w-full text-left text-xs">
        <thead className="bg-surface-container text-on-surface-variant">
          <tr>
            {block.headers.map((h, hi) => (
              <th key={hi} className="px-3 py-2.5 border-b border-outline-variant font-semibold whitespace-nowrap">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((r, ri) => {
            const rowMark = block.rowMarks[ri] ?? 'none'
            return (
              <tr key={ri} className={cn('border-b border-[rgba(196,198,205,.6)]', rowMark !== 'none' && rowMark !== 'change' && MARK_CELL[rowMark])}>
                {r.map((c, ci) => {
                  const cellMark = block.cellMarks[ri]?.[ci] ?? 'none'
                  return (
                    <td key={ci} className={cn(
                      'px-3 py-2 align-top',
                      ci === 0 ? 'text-secondary font-mono text-caption' : 'text-on-surface-variant',
                      MARK_CELL[cellMark],
                    )}>{c}</td>
                  )
                })}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ─── A pane's stack of blocks (or an empty-side placeholder) ─── */
export function BlocksPane({ blocks, emptyLabel }: { blocks: CompareBlock[]; emptyLabel: string }) {
  if (!blocks.length) {
    return <p className="text-on-surface-variant italic text-sm">{emptyLabel}</p>
  }
  return (
    <div className="space-y-3">
      {blocks.map((b, i) => <DiffBlockView key={i} block={b} />)}
    </div>
  )
}

/* ─── Flat-fallback markdown body → richtext / table blocks (legacy) ─── */
export function SectionBody({ content }: { content: string }) {
  const blocks = parseSectionBody(content)
  if (blocks.length === 0) {
    return <p className="text-on-surface-variant italic text-sm">No content.</p>
  }
  return (
    <div className="space-y-3">
      {blocks.map((b, i) =>
        b.type === 'table' ? (
          <div key={i} className="overflow-hidden border border-outline-variant rounded-lg">
            <table className="w-full text-left text-xs">
              <thead className="bg-surface-container text-on-surface-variant">
                <tr>
                  {b.headers.map((h, hi) => (
                    <th key={hi} className="px-3 py-2.5 border-b border-outline-variant font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri} className="border-b border-[rgba(196,198,205,.6)]">
                    {r.map((c, ci) => (
                      <td key={ci} className={cn('px-3 py-2', ci === 0 ? 'text-secondary font-mono text-caption' : 'text-on-surface-variant')}>{c}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p key={i} className="text-on-surface leading-relaxed text-sm whitespace-pre-line">{b.text}</p>
        ),
      )}
    </div>
  )
}
