import { useState } from 'react'
import { Icon, ScrollX } from '../../../components/ui'
import { useFunctionSource } from '../../../hooks/useProjects'
import { ApiError } from '../../../lib/http'

/* The function's own lines of code under its flowchart, so a reviewer can check the chart against
   the code (BACKLOG NW-7). Read only when opened, from the version's checkout on the server. */

export function FunctionCode({ projectId, versionId, functionId }: {
  projectId: string; versionId: string; functionId: string
}) {
  const [open, setOpen] = useState(false)
  const { data, isLoading, error } = useFunctionSource(projectId, versionId, functionId, open)
  return (
    <div className="mt-3">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 px-2.5 py-1 border border-outline-variant rounded-lg bg-surface-container-lowest font-mono text-label text-on-surface-variant hover:bg-surface-container-low"
      >
        <Icon name="code" size={13} />{open ? 'Hide code' : 'Show code'}
      </button>
      {open && (
        <div className="mt-2 border border-outline-variant rounded-lg overflow-hidden">
          {isLoading && <p className="px-3 py-2 font-mono text-caption text-outline">Loading the code…</p>}
          {error && (
            <p className="px-3 py-2 text-caption text-error flex items-center gap-1">
              <Icon name="error" size={12} />
              {error instanceof ApiError && error.code === 'SOURCE_NOT_HERE'
                ? error.message
                : 'Could not read the code of this function.'}
            </p>
          )}
          {data && (
            <>
              <p className="px-3 py-1.5 bg-surface-container font-mono text-label text-on-surface-variant">
                {data.file} · lines {data.startLine}–{data.endLine}
              </p>
              <ScrollX>
                <pre className="py-2 font-mono text-xs leading-relaxed text-on-surface">
                  <code>
                    {data.lines.map((line, i) => (
                      <div key={i} className="flex">
                        <span className="select-none w-12 flex-shrink-0 pr-3 text-right text-outline" aria-hidden>
                          {data.startLine + i}
                        </span>
                        <span className="whitespace-pre pr-3">{line}</span>
                      </div>
                    ))}
                  </code>
                </pre>
              </ScrollX>
              {data.truncated && (
                <p className="px-3 py-1.5 border-t border-outline-variant font-mono text-label text-outline">
                  Cut at {data.lines.length} lines; the function goes on to line {data.endLine}.
                </p>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
