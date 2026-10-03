import { memo, useState } from 'react'
import { Icon, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { BehaviorTableData, FlowchartTableData, RichSection, RichTable } from '../../../types'
import { useEdit } from '../editContext'
import { FlowchartFigure } from './FlowchartFigure'
import { SlotText } from './SlotText'

/* The SWE.3 document, section by section as its DOCX. Texts the LLM wrote carry their slot and
   render through SlotText, so edit mode can correct them in place. */

/* ── Rendered table section ── */
function TableView({ table }: { table: RichTable }) {
  return (
    <div className="overflow-x-auto border border-outline-variant rounded-lg">
      <table className="w-full text-left text-body">
        <thead className="bg-surface-container text-on-surface-variant">
          <tr>
            {table.headers.map((h, i) => (
              <th key={i} className="px-4 py-3 border-b border-outline-variant font-semibold">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody className="text-on-surface">
          {table.rows.map((r, ri) => (
            <tr key={ri} className="border-b border-outline-variant/60 last:border-0 hover:bg-surface-container-low">
              {r.map((c, ci) => {
                const slot = table.cellSlots?.[ri]?.[ci]
                return (
                  <td key={ci} className={cn('px-4 py-3 whitespace-pre-line align-top', ci === 0 && 'font-mono text-caption text-secondary', slot && 'min-w-[220px]')}>
                    {slot ? <SlotText slot={slot} display={c} /> : c}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* ── Diagram: rendered PNG (+ optional mermaid "view source") ── */
function DiagramView({ section }: { section: RichSection }) {
  const [showSrc, setShowSrc] = useState(false)
  return (
    <figure className="bg-surface-container-low border border-outline-variant rounded-lg overflow-hidden">
      {section.imageUrl ? (
        <img
          src={section.imageUrl}
          alt={section.title}
          loading="lazy"
          className="block w-full max-h-[440px] object-contain bg-white"
        />
      ) : (
        <div className="flex flex-col items-center justify-center text-center py-12 gap-3">
          <Icon name="account_tree" size={40} className="text-outline-variant" />
          <Text variant="caption" className="font-mono max-w-sm">{section.content ?? 'Diagram generated from the Clang AST'}</Text>
        </div>
      )}
      <figcaption className="flex items-center justify-between gap-2 px-3 py-2 border-t border-outline-variant bg-white">
        <Text variant="caption" className="font-mono truncate">{section.content ?? section.title}</Text>
        {section.mermaid && (
          <button
            onClick={() => setShowSrc((v) => !v)}
            className="flex items-center gap-1 flex-shrink-0 text-secondary hover:underline font-mono text-label"
          >
            <Icon name="code" size={13} />
            {showSrc ? 'Hide source' : 'View source'}
          </button>
        )}
      </figcaption>
      {showSrc && section.mermaid && (
        <pre className="px-3 py-2 bg-surface-container-low border-t border-outline-variant overflow-x-auto font-mono text-label text-on-surface-variant whitespace-pre">{section.mermaid}</pre>
      )}
    </figure>
  )
}

function KeyCell({ children, top }: { children: string; top?: boolean }) {
  return (
    <td className={cn('px-4 py-3 font-semibold text-on-surface-variant bg-surface-container w-40', top && 'align-top')}>{children}</td>
  )
}

/* ── Flowchart table (5-row layout mirroring docx_exporter flowchart table); each flowchart is an SVG ── */
function FlowchartTableView({ data }: { data: FlowchartTableData }) {
  const edit = useEdit()
  return (
    <div className="overflow-x-auto border border-outline-variant rounded-lg">
      <table className="w-full text-left text-body">
        <tbody>
          <tr className="border-b border-outline-variant/60">
            <KeyCell top>Requirements</KeyCell>
            <td className="px-4 py-3">
              {data.description && (
                <SlotText slot={data.descriptionSlot} display={data.description} className="text-body text-on-surface mb-3" />
              )}
              {data.flowcharts.map((fc, i) => (
                <div key={i} data-flowchart-id={fc.flowchartId ?? undefined} className={i > 0 ? 'mt-4' : ''}>
                  <div className="flex items-center justify-between gap-2 mb-1">
                    {fc.label && <p className="font-mono text-caption text-on-surface-variant truncate">{fc.label}</p>}
                    {edit?.editing && fc.editable && (
                      <button
                        type="button"
                        disabled={edit.locked}
                        onClick={() => edit.openFlowchart(fc)}
                        title={edit.labelsLocked ?? undefined}
                        className={cn(
                          'flex-shrink-0 flex items-center gap-1 px-2.5 py-1 border rounded-lg bg-white font-mono text-label font-semibold disabled:opacity-40',
                          edit.labelsLocked ? 'border-outline-variant text-outline' : 'border-secondary text-secondary hover:bg-surface-container-low',
                        )}
                      >
                        <Icon name={edit.labelsLocked ? 'lock' : 'account_tree'} size={13} />
                        Edit flowchart
                      </button>
                    )}
                  </div>
                  <FlowchartFigure chart={fc} />
                </div>
              ))}
            </td>
          </tr>
          <tr className="border-b border-outline-variant/60">
            <KeyCell>Risk</KeyCell>
            <td className="px-4 py-3">{data.risk}</td>
          </tr>
          <tr className="border-b border-outline-variant/60">
            <KeyCell>Capacity(Density)</KeyCell>
            <td className="px-4 py-3">{data.capacity}</td>
          </tr>
          <tr className="border-b border-outline-variant/60">
            <KeyCell>Input Name</KeyCell>
            <td className="px-4 py-3"><SlotText slot={data.inputNameSlot} display={data.inputName} /></td>
          </tr>
          <tr>
            <KeyCell>Output Name</KeyCell>
            <td className="px-4 py-3"><SlotText slot={data.outputNameSlot} display={data.outputName} /></td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

/* ── Behavior table (5-row layout + optional PNG diagram below) ── */
function BehaviorTableView({ data }: { data: BehaviorTableData }) {
  return (
    <div className="space-y-3">
      <div className="overflow-x-auto border border-outline-variant rounded-lg">
        <table className="w-full text-left text-body">
          <tbody>
            <tr className="border-b border-outline-variant/60">
              <KeyCell top>Requirements</KeyCell>
              <td className="px-4 py-3">
                {data.descriptionList.length > 0 && <p className="font-semibold text-on-surface mb-1">Behavior Description</p>}
                <SlotText
                  slot={data.descriptionSlot}
                  display={data.descriptionList.join('\n')}
                  bullets={data.descriptionList}
                  className="text-on-surface"
                />
              </td>
            </tr>
            <tr className="border-b border-outline-variant/60">
              <KeyCell>Risk</KeyCell>
              <td className="px-4 py-3">{data.risk}</td>
            </tr>
            <tr className="border-b border-outline-variant/60">
              <KeyCell>Capacity</KeyCell>
              <td className="px-4 py-3">{data.capacity}</td>
            </tr>
            <tr className="border-b border-outline-variant/60">
              <KeyCell>Input Name</KeyCell>
              <td className="px-4 py-3"><SlotText slot={data.inputNameSlot} display={data.inputName} /></td>
            </tr>
            <tr>
              <KeyCell>Output Name</KeyCell>
              <td className="px-4 py-3"><SlotText slot={data.outputNameSlot} display={data.outputName} /></td>
            </tr>
          </tbody>
        </table>
      </div>
      {data.diagramUrl && (
        <figure className="bg-surface-container-low border border-outline-variant rounded-lg overflow-hidden">
          <img src={data.diagramUrl} alt="Behaviour diagram" loading="lazy" className="block w-full max-h-[440px] object-contain bg-white" />
        </figure>
      )}
    </div>
  )
}

/* ── One rich section (richtext | table | diagram | flowchart_table | behavior_table) + nested children ──
   Memoised: a document can hold 500+ functions, and the page re-renders on every job poll. */
export const RichSectionView = memo(function RichSectionView({ section, depth = 0 }: { section: RichSection; depth?: number }) {
  const headingSize = depth === 0 ? 'text-[20px]' : depth === 1 ? 'text-[17px]' : 'text-[15px]'
  return (
    <section id={`sec-${section.id}`} className="scroll-mt-16">
      <div className="flex items-baseline gap-2 mb-4">
        {section.number && <span className="font-mono text-caption text-outline flex-shrink-0">{section.number}</span>}
        <h2 className={cn('font-semibold text-on-surface', headingSize)}>{section.title}</h2>
      </div>
      {section.type === 'table' && section.table ? (
        <TableView table={section.table} />
      ) : section.type === 'diagram' ? (
        <DiagramView section={section} />
      ) : section.type === 'flowchart_table' && section.flowchartTable ? (
        <FlowchartTableView data={section.flowchartTable} />
      ) : section.type === 'behavior_table' && section.behaviorTable ? (
        <BehaviorTableView data={section.behaviorTable} />
      ) : section.content ? (
        section.contentSlot
          ? <SlotText slot={section.contentSlot} display={section.content} className="text-sm text-on-surface leading-relaxed" />
          : <p className="text-sm text-on-surface leading-relaxed whitespace-pre-line">{section.content}</p>
      ) : null}
      {section.children.length > 0 && (
        <div className="mt-8 space-y-8 pl-4 border-l border-outline-variant">
          {section.children.map((c) => <RichSectionView key={c.id} section={c} depth={depth + 1} />)}
        </div>
      )}
    </section>
  )
})
