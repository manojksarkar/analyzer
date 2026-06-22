import { useState, useRef, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useDocuments } from '../hooks/useProjects'
import { TableSkeleton } from '../components/ui'
import { ProcessBadge } from '../components/ui/Badge'
import type { DocStatus, Document } from '../types'

const PROCESSES = ['All', 'SYS.1', 'SYS.2', 'SWE.1', 'SWE.2', 'SWE.3']

/* status → {label, icon, styles} (matches design .badge-*) */
const STATUS_BADGE: Record<string, { label: string; icon: string; bg: string; color: string; border: string }> = {
  approved:  { label: 'Approved',  icon: 'check_circle',    bg: '#f0fdf9', color: '#00a572', border: '#86efac' },
  in_review: { label: 'In Review', icon: 'rate_review',     bg: '#fff8e6', color: '#b45309', border: '#f59e0b' },
  complete:  { label: 'Approved',  icon: 'check_circle',    bg: '#f0fdf9', color: '#00a572', border: '#86efac' },
  unchanged: { label: 'Unchanged', icon: 'horizontal_rule', bg: '#f3f4f6', color: '#74777d', border: '#c4c6cd' },
  draft:     { label: 'Unchanged', icon: 'horizontal_rule', bg: '#f3f4f6', color: '#74777d', border: '#c4c6cd' },
}

function StatusBadge({ status }: { status: DocStatus }) {
  const s = STATUS_BADGE[status] ?? STATUS_BADGE.unchanged
  return (
    <span
      className="inline-flex items-center gap-1 uppercase"
      style={{
        padding: '2px 8px', borderRadius: 3, fontSize: 10, fontWeight: 700,
        fontFamily: "'JetBrains Mono'", letterSpacing: '0.04em', whiteSpace: 'nowrap',
        background: s.bg, color: s.color, border: `1px solid ${s.border}`,
      }}
    >
      <span className="material-symbols-outlined" style={{ fontSize: 10 }} aria-hidden>{s.icon}</span>
      {s.label}
    </span>
  )
}

/* Normalize the various DocStatus values into the 3 filterable buckets */
function statusBucket(s: DocStatus): 'approved' | 'in_review' | 'unchanged' {
  if (s === 'approved' || s === 'complete') return 'approved'
  if (s === 'in_review') return 'in_review'
  return 'unchanged'
}

export function DocumentsPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const { data: project } = useProject(projectId ?? '')
  const { data: documents, isLoading } = useDocuments(projectId ?? '')

  const [activeProcess, setActiveProcess] = useState('All')
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<Set<'approved' | 'in_review' | 'unchanged'>>(new Set())
  const [statusOpen, setStatusOpen] = useState(false)
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const statusRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    function onDown(e: MouseEvent) {
      if (statusRef.current && !statusRef.current.contains(e.target as Node)) setStatusOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [])

  const all = documents ?? []
  const filtered = all.filter((d) => {
    if (activeProcess !== 'All' && d.process !== activeProcess) return false
    if (statusFilter.size > 0 && !statusFilter.has(statusBucket(d.status))) return false
    if (search && !d.name.toLowerCase().includes(search.toLowerCase())) return false
    return true
  })

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }
  function toggleStatus(s: 'approved' | 'in_review' | 'unchanged') {
    setStatusFilter((prev) => {
      const next = new Set(prev)
      next.has(s) ? next.delete(s) : next.add(s)
      return next
    })
  }

  const allSelected = selected.size === filtered.length && filtered.length > 0
  const someSelected = selected.size > 0 && !allSelected

  return (
    <div className="flex-1 overflow-y-auto" style={{ background: '#eff4ff' }}>
      <div className="p-6">
        <div className="bg-white border border-outline-variant rounded-xl overflow-hidden">

          {/* ── Card header ── */}
          <div className="px-5 pt-4 pb-0 border-b border-outline-variant">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h2 className="text-on-surface font-semibold" style={{ fontSize: 18 }}>Documents</h2>
                <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                  {filtered.length} document{filtered.length !== 1 ? 's' : ''} · v1.2.0 · {project?.name ?? '…'}
                </p>
              </div>
              <div className="flex items-center gap-2">
                {/* Status filter */}
                <div className="relative" ref={statusRef}>
                  <button
                    onClick={() => setStatusOpen((v) => !v)}
                    className="flex items-center gap-1.5 px-3 py-2 border border-outline-variant rounded-lg bg-white hover:bg-surface-container-low transition-colors"
                    style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, color: '#44474c' }}
                  >
                    <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 14 }} aria-hidden>filter_list</span>
                    {statusFilter.size > 0 ? `Status (${statusFilter.size})` : 'Status'}
                    <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 13 }} aria-hidden>expand_more</span>
                  </button>
                  {statusOpen && (
                    <div
                      className="absolute right-0 bg-white border border-outline-variant rounded-lg overflow-hidden"
                      style={{ top: 'calc(100% + 6px)', zIndex: 200, boxShadow: '0 4px 20px rgba(4,22,39,.12)', minWidth: 180 }}
                    >
                      <div className="py-1.5">
                        {([['approved', 'Approved'], ['in_review', 'In Review'], ['unchanged', 'Unchanged']] as const).map(([key, label]) => (
                          <button
                            key={key}
                            onClick={() => toggleStatus(key)}
                            className="w-full flex items-center justify-between px-3 py-2 hover:bg-surface-container-low text-on-surface"
                            style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}
                          >
                            <span>{label}</span>
                            {statusFilter.has(key) && (
                              <span className="material-symbols-outlined text-secondary" style={{ fontSize: 14 }} aria-hidden>check</span>
                            )}
                          </button>
                        ))}
                      </div>
                      <div className="border-t border-outline-variant py-1">
                        <button
                          onClick={() => setStatusFilter(new Set())}
                          className="w-full text-left px-3 py-2 hover:bg-surface-container-low text-on-surface-variant"
                          style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}
                        >
                          Clear filter
                        </button>
                      </div>
                    </div>
                  )}
                </div>
                {/* Search */}
                <div
                  className="flex items-center gap-1.5 px-2.5 py-1.5 border border-outline-variant rounded-lg bg-white hover:border-secondary transition-colors"
                  style={{ minWidth: 180 }}
                >
                  <span className="material-symbols-outlined text-on-surface-variant flex-shrink-0" style={{ fontSize: 14 }} aria-hidden>search</span>
                  <input
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    type="text"
                    placeholder="Search documents…"
                    className="flex-1 bg-transparent outline-none text-on-surface placeholder:text-on-surface-variant"
                    style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}
                  />
                </div>
              </div>
            </div>

            {/* Process tabs */}
            <div className="flex items-center -mb-px overflow-x-auto" role="tablist" aria-label="Filter by process">
              {PROCESSES.map((p) => {
                const active = activeProcess === p
                return (
                  <button
                    key={p}
                    role="tab"
                    aria-selected={active}
                    onClick={() => setActiveProcess(p)}
                    className="transition-colors whitespace-nowrap"
                    style={{
                      padding: '8px 14px',
                      borderBottom: active ? '2px solid #0058be' : '2px solid transparent',
                      fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 600,
                      color: active ? '#0058be' : '#74777d',
                    }}
                  >
                    {p}
                  </button>
                )
              })}
            </div>
          </div>

          {/* ── Batch bar ── */}
          {selected.size > 0 && (
            <div className="bg-secondary border-b border-secondary-container px-5 py-2.5 flex items-center justify-between" role="toolbar" aria-label="Bulk actions">
              <div className="flex items-center gap-3">
                <span className="text-on-secondary font-semibold" style={{ fontFamily: "'JetBrains Mono'", fontSize: 12 }}>
                  {selected.size} selected
                </span>
                <div className="w-px h-4 bg-on-secondary opacity-30" aria-hidden />
                {[['download', 'Download'], ['person_add', 'Assign'], ['task_alt', 'Approve']].map(([icon, label]) => (
                  <button
                    key={label}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors text-on-secondary"
                    style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, background: 'rgba(255,255,255,.12)' }}
                  >
                    <span className="material-symbols-outlined" style={{ fontSize: 13 }} aria-hidden>{icon}</span>
                    {label}
                  </button>
                ))}
              </div>
              <button
                onClick={() => setSelected(new Set())}
                className="flex items-center gap-1 text-on-secondary opacity-70 hover:opacity-100 transition-opacity"
                style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}
              >
                <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden>close</span>
                Clear
              </button>
            </div>
          )}

          {/* ── Table ── */}
          <div className="overflow-x-auto">
            {isLoading ? (
              <TableSkeleton rows={8} cols={8} />
            ) : (
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container-low border-b border-outline-variant">
                    <th className="px-4 py-3" style={{ width: 40 }}>
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={allSelected}
                        ref={(el) => { if (el) el.indeterminate = someSelected }}
                        onChange={(e) => setSelected(e.target.checked ? new Set(filtered.map((d) => d.id)) : new Set())}
                        style={{ accentColor: '#0058be', width: 15, height: 15, cursor: 'pointer' }}
                      />
                    </th>
                    {[['Document', undefined], ['Process', 100], ['Version', 90], ['Assignee', 155], ['Status', 110], ['Due Date', 100], ['', 90]].map(([h, w], i) => (
                      <th
                        key={i}
                        className="text-left px-4 py-3 text-on-surface-variant uppercase"
                        style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, fontWeight: 500, letterSpacing: '0.07em', width: w as number | undefined }}
                      >
                        {h as string}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((doc) => (
                    <DocRow
                      key={doc.id}
                      doc={doc}
                      selected={selected.has(doc.id)}
                      onToggle={() => toggle(doc.id)}
                      onOpen={() => navigate(`/projects/${projectId}/compare`)}
                    />
                  ))}
                </tbody>
              </table>
            )}

            {!isLoading && filtered.length === 0 && (
              <div className="py-14 flex flex-col items-center text-center gap-4">
                <div className="w-12 h-12 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
                  <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 24 }} aria-hidden>search_off</span>
                </div>
                <div>
                  <p className="text-on-surface font-medium" style={{ fontSize: 14 }}>No documents found</p>
                  <p className="text-on-surface-variant mt-1" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>
                    Try a different process, status, or search term.
                  </p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

/* ── Single row ── */
function DocRow({ doc, selected, onToggle, onOpen }: { doc: Document; selected: boolean; onToggle: () => void; onOpen: () => void }) {
  const isUnchanged = statusBucket(doc.status) === 'unchanged'
  return (
    <tr
      className="border-b border-outline-variant last:border-0 cursor-pointer transition-colors"
      style={{ background: selected ? '#eff4ff' : undefined }}
      onClick={onOpen}
    >
      <td className="px-4 py-3.5 text-center" onClick={(e) => e.stopPropagation()}>
        <input
          type="checkbox"
          aria-label={`Select ${doc.name}`}
          checked={selected}
          onChange={onToggle}
          style={{ accentColor: '#0058be', width: 15, height: 15, cursor: 'pointer' }}
        />
      </td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-surface-container-low border border-outline-variant flex items-center justify-center flex-shrink-0">
            <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 15 }} aria-hidden>article</span>
          </div>
          <div>
            <p className="text-on-surface hover:text-secondary transition-colors" style={{ fontFamily: "'JetBrains Mono'", fontSize: 13, fontWeight: 500 }}>{doc.name}</p>
            <p className="text-on-surface-variant mt-0.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11 }}>{doc.subtitle}</p>
          </div>
        </div>
      </td>
      <td className="px-4 py-3.5"><ProcessBadge process={doc.process} /></td>
      <td className="px-4 py-3.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, color: '#44474c' }}>{doc.version}</td>
      <td className="px-4 py-3.5">
        {doc.assignee ? (
          <div className="flex items-center gap-2">
            <div className="w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0" style={{ background: doc.assigneeColor }}>
              <span className="font-bold" style={{ fontSize: 9, fontFamily: 'Inter', color: doc.assigneeTextColor }}>{doc.assigneeInitials}</span>
            </div>
            <span className="text-on-surface truncate" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, maxWidth: 100 }}>{doc.assignee}</span>
          </div>
        ) : (
          <span className="text-outline" style={{ fontSize: 12 }}>—</span>
        )}
      </td>
      <td className="px-4 py-3.5"><StatusBadge status={doc.status} /></td>
      <td className="px-4 py-3.5" style={{ fontFamily: "'JetBrains Mono'", fontSize: 11, color: '#74777d' }}>{doc.due}</td>
      <td className="px-4 py-3.5" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-1">
          <button onClick={onOpen} title="View" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-secondary">
            <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden>open_in_new</span>
          </button>
          <button title="Download DOCX" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
            <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden>download</span>
          </button>
          {isUnchanged ? (
            <span title="No changes from reference" className="p-1.5 flex items-center cursor-not-allowed" style={{ color: '#c4c6cd' }}>
              <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden>compare_arrows</span>
            </span>
          ) : (
            <button onClick={onOpen} title="Compare vs reference" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
              <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden>compare_arrows</span>
            </button>
          )}
          <button title="More" className="p-1.5 hover:bg-surface-container rounded-lg transition-colors text-on-surface-variant">
            <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden>more_vert</span>
          </button>
        </div>
      </td>
    </tr>
  )
}
