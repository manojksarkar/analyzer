import { useState } from 'react'
import { Icon, Modal } from '../../../components/ui'
import { useFunctionSource } from '../../../hooks/useProjects'
import { ApiError } from '../../../lib/http'
import type { FlowchartEntry } from '../../../types'

/* A function's flowchart and its code side by side, so a reviewer can check the chart against the
   code (BACKLOG NW-7; docs/ui-mockups/documents.html#code). View code beside the chart opens it; the
   code is read from the version's checkout on the server only then. */

export function FunctionCode({ projectId, versionId, functionId, title, flowcharts }: {
  projectId: string; versionId: string; functionId: string
  /** The function's name as the document prints it. */
  title: string
  flowcharts: FlowchartEntry[]
}) {
  const [open, setOpen] = useState(false)
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        title="The flowchart and its code, side by side"
        className="flex-shrink-0 flex items-center gap-1 px-2.5 py-1 border border-outline-variant rounded-lg bg-surface-container-lowest font-mono text-label font-semibold text-on-surface-variant hover:text-secondary hover:border-secondary hover:bg-surface-container-low"
      >
        <Icon name="code" size={13} />View code
      </button>
      {open && (
        <FunctionCodeDialog projectId={projectId} versionId={versionId} functionId={functionId}
                            title={title} flowcharts={flowcharts} onClose={() => setOpen(false)} />
      )}
    </>
  )
}

function FunctionCodeDialog({ projectId, versionId, functionId, title, flowcharts, onClose }: {
  projectId: string; versionId: string; functionId: string; title: string
  flowcharts: FlowchartEntry[]; onClose: () => void
}) {
  const { data, isLoading, error } = useFunctionSource(projectId, versionId, functionId, true)
  return (
    <Modal
      open
      onClose={onClose}
      title={`${title} — flowchart and code`}
      description={data ? `${data.file} · lines ${data.startLine}–${data.endLine}` : undefined}
      className="max-w-none w-[calc(100vw-48px)] h-[calc(100vh-48px)] p-0 flex flex-col overflow-hidden"
      headerClassName="mb-0 px-4 py-3 border-b border-outline-variant"
    >
      <div className="flex-1 min-h-0 grid grid-cols-2">
        <section aria-label="Flowchart" className="min-h-0 overflow-auto">
          <PaneLabel>Flowchart</PaneLabel>
          <div className="p-4 flex flex-col items-center gap-4">
            {flowcharts.map((fc, i) => fc.status === 'drawn' && fc.imageUrl ? (
              <img key={i} src={fc.imageUrl} alt={`Flowchart of ${fc.label}`}
                   className="doc-picture block max-w-full h-auto bg-white rounded" />
            ) : (
              <p key={i} className="font-mono text-caption text-outline">
                {fc.status === 'too_large' ? `Too large to draw (${fc.boxes} boxes)` : 'Flowchart not drawn for this run'}
              </p>
            ))}
          </div>
        </section>
        <section aria-label="Code" className="min-h-0 overflow-auto border-l border-outline-variant">
          <PaneLabel>Code</PaneLabel>
          {isLoading && <p className="px-4 py-3 font-mono text-caption text-outline">Loading the code…</p>}
          {error && (
            <p className="px-4 py-3 text-caption text-error flex items-center gap-1">
              <Icon name="error" size={12} />
              {error instanceof ApiError && error.code === 'SOURCE_NOT_HERE'
                ? error.message
                : 'Could not read the code of this function.'}
            </p>
          )}
          {data && (
            <>
              {/* No ligatures: `!=` stays `!=`, as the code has it. */}
              <pre className="py-2 font-mono text-xs leading-relaxed text-on-surface [font-variant-ligatures:none]">
                <code>
                  {data.lines.map((line, i) => (
                    <div key={i} className="flex">
                      <span className="select-none w-12 flex-shrink-0 pr-3 text-right text-outline" aria-hidden>
                        {data.startLine + i}
                      </span>
                      <span className="whitespace-pre pr-4">{line}</span>
                    </div>
                  ))}
                </code>
              </pre>
              {data.truncated && (
                <p className="px-4 py-1.5 border-t border-outline-variant font-mono text-label text-outline">
                  Cut at {data.lines.length} lines; the function goes on to line {data.endLine}.
                </p>
              )}
            </>
          )}
        </section>
      </div>
    </Modal>
  )
}

function PaneLabel({ children }: { children: string }) {
  return (
    <p className="sticky top-0 z-10 px-3 py-1.5 bg-surface-container-low border-b border-outline-variant font-mono text-label font-semibold uppercase tracking-[0.08em] text-on-surface-variant">
      {children}
    </p>
  )
}
