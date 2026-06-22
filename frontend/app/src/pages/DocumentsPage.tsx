import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useDocuments } from '../hooks/useProjects'
import { Button, Badge, ProcessBadge, Checkbox, TableSkeleton } from '../components/ui'
import type { DocStatus } from '../types'

const PROCESSES = ['All', 'SYS.1', 'SYS.2', 'SWE.1', 'SWE.2', 'SWE.3', 'SWE.4', 'SWE.5']

const STATUS_CONFIG: Record<DocStatus, { label: string; variant: 'warning' | 'success' | 'primary' | 'default' }> = {
  in_review: { label: 'In Review', variant: 'warning' },
  approved:  { label: 'Approved',  variant: 'success' },
  complete:  { label: 'Complete',  variant: 'primary' },
  draft:     { label: 'Draft',     variant: 'default' },
}

export function DocumentsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [activeProcess, setActiveProcess] = useState('All')
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const { data: documents, isLoading } = useDocuments(projectId ?? '')
  const filtered = documents?.filter((d) => activeProcess === 'All' || d.process === activeProcess) ?? []

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const allSelected = selected.size === filtered.length && filtered.length > 0
  const someSelected = selected.size > 0 && !allSelected

  return (
    <div className="p-6">
      {/* Process filter tabs */}
      <div className="flex items-center gap-1 mb-5 flex-wrap" role="tablist" aria-label="Filter by process">
        {PROCESSES.map((p) => (
          <button
            key={p}
            role="tab"
            aria-selected={activeProcess === p}
            onClick={() => setActiveProcess(p)}
            className={`px-3 h-8 rounded-lg text-xs font-semibold transition-colors ${
              activeProcess === p
                ? 'bg-secondary text-white shadow-sm'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
          >
            {p}
          </button>
        ))}
      </div>

      {/* Batch action bar */}
      {selected.size > 0 && (
        <div role="toolbar" aria-label="Bulk actions" className="flex items-center gap-3 mb-4 px-4 py-2.5 bg-secondary/5 border border-secondary/20 rounded-xl">
          <span className="text-sm text-secondary font-semibold">{selected.size} selected</span>
          <div className="flex items-center gap-2 ml-2">
            <Button variant="outline" size="sm">
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>download</span>
              Download
            </Button>
            <Button variant="outline" size="sm">
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>person</span>
              Assign
            </Button>
            <Button variant="outline" size="sm">
              <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>check</span>
              Approve
            </Button>
          </div>
          <button
            onClick={() => setSelected(new Set())}
            className="ml-auto text-xs text-on-surface-variant hover:text-on-surface transition-colors"
          >
            Clear
          </button>
        </div>
      )}

      {/* Table */}
      <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">
        {isLoading ? (
          <TableSkeleton rows={6} cols={7} />
        ) : (
          <table className="w-full">
            <thead className="sticky top-0">
              <tr className="bg-surface-container-low border-b border-outline-variant">
                <th className="w-10 px-4 py-3">
                  <Checkbox
                    checked={allSelected ? true : someSelected ? 'indeterminate' : false}
                    onCheckedChange={(v) =>
                      setSelected(v === true ? new Set(filtered.map((d) => d.id)) : new Set())
                    }
                  />
                </th>
                {['Document', 'Process', 'Status', 'Assignee', 'Version', 'Updated', ''].map((h) => (
                  <th key={h} className="text-left px-4 py-3 font-mono text-[11px] text-on-surface-variant uppercase tracking-[0.06em] whitespace-nowrap">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {filtered.map((doc) => (
                <tr
                  key={doc.id}
                  className="border-b border-outline-variant last:border-0 hover:bg-surface-container-low/50 transition-colors group"
                >
                  <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                    <Checkbox
                      checked={selected.has(doc.id)}
                      onCheckedChange={() => toggle(doc.id)}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <button
                      onClick={() => navigate(`/projects/${projectId}/compare`)}
                      className="text-sm font-medium text-on-surface hover:text-secondary transition-colors text-left"
                    >
                      {doc.name}
                    </button>
                  </td>
                  <td className="px-4 py-3"><ProcessBadge process={doc.process} /></td>
                  <td className="px-4 py-3">
                    <Badge variant={STATUS_CONFIG[doc.status].variant}>{STATUS_CONFIG[doc.status].label}</Badge>
                  </td>
                  <td className="px-4 py-3 text-xs text-on-surface-variant">{doc.assignee ?? '—'}</td>
                  <td className="px-4 py-3">
                    <span className="font-mono text-[10px] text-on-surface-variant">{doc.version}</span>
                  </td>
                  <td className="px-4 py-3 text-xs text-on-surface-variant">{doc.updatedAt}</td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={() => navigate(`/projects/${projectId}/compare`)}
                        className="p-1 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant"
                        title="Compare"
                        aria-label={`Compare ${doc.name}`}
                      >
                        <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>compare_arrows</span>
                      </button>
                      <button
                        className="p-1 rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant"
                        title="Download"
                        aria-label={`Download ${doc.name}`}
                      >
                        <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>download</span>
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center text-sm text-on-surface-variant">
                    No documents for process <strong>{activeProcess}</strong>.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
