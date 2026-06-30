import { useState, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useDocument, useDocuments, useDocumentRender, useTeam, useProject } from '../hooks/useProjects'
import { useProjectViewState } from '../hooks/useProjectViewState'
import {
  useApproveDoc, useSelfAssign, useAssignReviewers, useDownloadDoc,
} from '../hooks/useDocumentMutations'
import { useAuthStore } from '../store/auth'
import { DocTreePanel } from '../components/shell/DocTreePanel'
import { groupDocsByProcess, buildAssigneeOptions } from '../lib/docTree'
import { Card, Icon, Skeleton, Text } from '../components/ui'
import { cn } from '../lib/cn'
import type { DocSection, SectionReviewState, RichSection, RichTable, DocMeta, TeamMember, FlowchartTableData, BehaviorTableData } from '../types'

/* review_state → outline/tracker icon */
const SECTION_STATE: Record<SectionReviewState, { icon: string; cls: string }> = {
  accepted: { icon: 'check_circle',           cls: 'text-[#00a572]' },
  edited:   { icon: 'edit',                   cls: 'text-secondary' },
  declined: { icon: 'cancel',                 cls: 'text-error' },
}
function sectionStateIcon(s: SectionReviewState | null) {
  return s ? SECTION_STATE[s] : { icon: 'radio_button_unchecked', cls: 'text-outline' }
}

export function DocumentInspectorPage() {
  const { projectId, docId } = useParams<{ projectId: string; docId: string }>()
  const pid = projectId ?? ''
  const navigate = useNavigate()

  const { data: project } = useProject(pid)
  const { data: doc, isLoading } = useDocument(pid, docId ?? '')
  const { data: rich } = useDocumentRender(pid, docId ?? '')
  const { data: team } = useTeam(pid)
  const { viewVersion, selectedCommit } = useProjectViewState(pid)
  // The left rail lists every doc in the displayed version (same source as the
  // Documents page) so you can jump between documents without going back.
  const { data: railDocs } = useDocuments(pid, viewVersion?.id ? { versionId: viewVersion.id } : undefined)

  const approveDoc = useApproveDoc(pid)
  const selfAssign = useSelfAssign(pid)
  const assignReviewers = useAssignReviewers(pid)
  const downloadDoc = useDownloadDoc(pid)

  const isAdmin = project?.userRole === 'admin'
  const isDeveloper = project?.userRole === 'developer'
  const meName = useAuthStore((s) => s.user?.name ?? '')

  const canvasRef = useRef<HTMLElement>(null)
  const [assignOpen, setAssignOpen] = useState(false)
  const [assigneeFilter, setAssigneeFilter] = useState<string | null>(null)

  // Rail data (assignee filter shared with the dropdown, mirrors DocumentsPage).
  const allRailDocs = railDocs ?? []
  const railAssignee = assigneeFilter ?? (isDeveloper ? meName : '')
  const railGroups = groupDocsByProcess(railAssignee ? allRailDocs.filter((d) => d.assignee === railAssignee) : allRailDocs)
  const railAssignees = buildAssigneeOptions(allRailDocs)

  function scrollToSection(key: string) {
    canvasRef.current?.querySelector(`#sec-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  if (isLoading) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="max-w-3xl mx-auto px-6 py-8 space-y-4">
          <Skeleton className="h-10 w-2/3" />
          <Skeleton className="h-4 w-1/3" />
          <Skeleton className="h-64" />
        </div>
      </div>
    )
  }

  if (!doc) {
    return (
      <div className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="p-6">
          <Card className="py-20 flex flex-col items-center text-center gap-4">
            <Icon name="error_outline" size={32} className="text-on-surface-variant" />
            <div>
              <Text as="p" variant="heading" className="text-on-surface">Document not found</Text>
              <Text as="p" variant="caption" className="font-mono mt-1">It may have been removed or never generated.</Text>
            </div>
            <button
              onClick={() => navigate(`/projects/${pid}/documents`)}
              className="flex items-center gap-1.5 px-4 py-2 border border-outline-variant rounded-lg hover:bg-surface-container transition-colors font-mono text-caption text-on-surface-variant"
            >
              <Icon name="arrow_back" size={15} />
              Back to documents
            </button>
          </Card>
        </div>
      </div>
    )
  }

  const inReview = doc.status === 'in_review'
  const isUnchanged = doc.status === 'unchanged' || doc.status === 'draft'
  const refLabel = viewVersion?.tag ?? selectedCommit?.shortSha ?? doc.version
  const assignedToMe = !!meName && doc.assignee === meName
  const members = (team ?? []).filter((m) => !m.pending)

  return (
    <div className="flex-1 flex overflow-hidden min-h-0 relative">

      {/* ── Left document-tree rail (same as the Documents page) ── */}
      <DocTreePanel
        groups={railGroups}
        assigneeOptions={railAssignees}
        effectiveAssignee={railAssignee}
        meName={meName}
        isDeveloper={!!isDeveloper}
        activeDocId={doc.id}
        onPickAssignee={setAssigneeFilter}
        onOpenDoc={(d) => navigate(`/projects/${pid}/documents/${d.id}`)}
      />

      {/* ── Document canvas ── */}
      <main ref={canvasRef} className="flex-1 overflow-y-auto bg-surface-container-low">
        <div className="max-w-3xl mx-auto px-6 py-8">
          <div className="bg-white rounded-xl border border-outline-variant overflow-hidden shadow-[0_1px_4px_rgba(4,22,39,.06)]">

            {/* Cover header */}
            <div className="px-12 pt-10 pb-8 border-b border-outline-variant">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <Text as="p" variant="label" className="text-on-surface-variant tracking-[0.1em] mb-2">
                    {(rich?.cover.process ?? doc.process)} · <span className="font-mono">{rich?.cover.version ?? refLabel}</span>
                  </Text>
                  <h1 className="text-[28px] font-bold leading-tight tracking-[-0.02em] text-on-surface">{doc.name}</h1>
                  <p className="text-sm text-on-surface-variant mt-1">{rich?.cover.subtitle ?? doc.subtitle ?? 'Software Detailed Design Specification'}</p>
                  {rich && (
                    <div className="flex flex-wrap items-center gap-1.5 mt-3">
                      {[rich.cover.projectName, rich.cover.layer, rich.cover.group, rich.cover.standard]
                        .filter(Boolean)
                        .map((t, i) => (
                          <span key={i} className="font-mono text-label text-on-surface-variant bg-surface-container-low border border-outline-variant rounded px-1.5 py-0.5">{t}</span>
                        ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1.5 flex-shrink-0">
                  <button
                    onClick={() => downloadDoc(doc.id, `software_detailed_design_${rich?.cover.group ?? doc.name}`)}
                    className="flex items-center gap-1.5 px-3 py-2 bg-secondary hover:bg-secondary-container text-white rounded-lg transition-colors font-mono text-caption font-medium"
                  >
                    <Icon name="download" size={15} />
                    DOCX
                  </button>
                  {!isUnchanged && (
                    <button
                      onClick={() => navigate(`/projects/${pid}/compare`)}
                      title="Compare vs reference"
                      className="flex items-center gap-1.5 px-3 py-2 border border-outline-variant hover:border-secondary hover:text-secondary text-on-surface-variant rounded-lg transition-colors font-mono text-caption font-medium"
                    >
                      <Icon name="compare_arrows" size={15} />
                      Compare
                    </button>
                  )}
                </div>
              </div>
            </div>

            {/* Meta banner — pipeline/model availability + counts */}
            {rich && <MetaBanner meta={rich.meta} />}

            {/* Sections */}
            <div className="px-12 py-10 space-y-12">
              {!rich ? (
                <div className="space-y-4">
                  <Skeleton className="h-6 w-1/3" />
                  <Skeleton className="h-24" />
                  <Skeleton className="h-24" />
                </div>
              ) : rich.sections.length === 0 ? (
                <div className="bg-surface-container-low border border-outline-variant rounded-lg flex flex-col items-center text-center py-14 gap-3">
                  <Icon name="description" size={40} className="text-outline-variant" />
                  <Text as="p" variant="caption" className="font-mono">No section content for this document yet.</Text>
                </div>
              ) : (
                rich.sections.map((s) => <RichSectionView key={s.id} section={s} />)
              )}
            </div>
          </div>
        </div>
      </main>

      {/* ── Right panel: review tracker (in review) or outline ── */}
      <aside className="w-48 flex-shrink-0 bg-white border-l border-outline-variant flex flex-col overflow-hidden">
        <div className="px-3 py-3 border-b border-outline-variant flex-shrink-0">
          <Text variant="label" className="block text-on-surface-variant tracking-[0.1em]">
            {inReview ? 'Review Status' : 'On this page'}
          </Text>
        </div>

        {inReview ? (
          <ReviewTracker
            sections={doc.sections}
            progress={doc.reviewProgress}
            reviewer={doc.assignee}
            reviewerInitials={doc.assigneeInitials}
            isAdmin={!!isAdmin}
            assignedToMe={assignedToMe}
            onMarkComplete={() => approveDoc.mutate(doc.id)}
            onReassign={() => setAssignOpen(true)}
            onAssignToMe={() => selfAssign.mutate(doc.id)}
            onJump={scrollToSection}
          />
        ) : (
          <nav className="flex-1 overflow-y-auto py-2 px-2 space-y-0.5">
            {(rich?.toc ?? []).map((t) => (
              <button
                key={t.id}
                onClick={() => scrollToSection(t.id)}
                className={cn(
                  'w-full flex items-baseline gap-1.5 text-left px-2 py-1.5 rounded-lg text-body text-on-surface-variant hover:text-on-surface hover:bg-surface-container-low transition-colors',
                  t.level > 1 && 'pl-5',
                )}
              >
                <span className="font-mono text-label text-outline flex-shrink-0">{t.number}</span>
                <span className="truncate">{t.title}</span>
              </button>
            ))}
          </nav>
        )}
      </aside>

      {/* ── Assign reviewers slide-in ── */}
      {assignOpen && (
        <AssignReviewersPanel
          members={members}
          refLabel={refLabel}
          shortSha={selectedCommit?.shortSha ?? viewVersion?.shortSha}
          busy={assignReviewers.isPending}
          onClose={() => setAssignOpen(false)}
          onAssign={(userId) =>
            assignReviewers.mutate({ docId: doc.id, userIds: [userId] }, { onSuccess: () => setAssignOpen(false) })
          }
        />
      )}
    </div>
  )
}

/* ── Meta banner: pipeline/model availability + model counts ── */
function MetaBanner({ meta }: { meta: DocMeta }) {
  const stats: [string, number][] = [
    ['Units', meta.unitsTotal],
    ['Functions', meta.functionsTotal],
    ['Globals', meta.globalsTotal],
    ['Components', meta.components.length],
    ['Layers', meta.layers.length],
  ]
  return (
    <div className="px-12 py-3 border-b border-outline-variant bg-surface-container-low flex flex-wrap items-center gap-x-5 gap-y-1.5">
      <span className="flex items-center gap-1.5 font-mono text-label uppercase tracking-[0.06em] text-on-surface-variant">
        <Icon
          name={meta.source === 'pipeline' ? 'bolt' : 'dataset'}
          size={13}
          className={meta.pipelineDataAvailable ? 'text-[#00a572]' : 'text-outline'}
        />
        Source: {meta.source}
      </span>
      {stats.map(([label, value]) => (
        <span key={label} className="font-mono text-label text-on-surface-variant">
          <span className="text-on-surface font-semibold">{value}</span> {label}
        </span>
      ))}
    </div>
  )
}

/* ── Rendered table section ── */
function TableView({ table }: { table: RichTable }) {
  return (
    <div className="overflow-hidden border border-outline-variant rounded-lg">
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
              {r.map((c, ci) => (
                <td key={ci} className={cn('px-4 py-3', ci === 0 && 'font-mono text-caption text-secondary')}>{c}</td>
              ))}
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

/* ── Flowchart table (5-row layout mirroring docx_exporter flowchart table) ── */
function FlowchartTableView({ data }: { data: FlowchartTableData }) {
  return (
    <div className="overflow-hidden border border-outline-variant rounded-lg">
      <table className="w-full text-left text-body">
        <tbody>
          <tr className="border-b border-outline-variant/60">
            <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container align-top w-40">Requirements</td>
            <td className="px-4 py-3">
              {data.description && <p className="text-body text-on-surface mb-3">{data.description}</p>}
              {data.flowcharts.map((fc, i) => (
                <div key={i} className={i > 0 ? 'mt-4' : ''}>
                  {fc.label && <p className="font-mono text-caption text-on-surface-variant mb-1">{fc.label}</p>}
                  {fc.imageUrl ? (
                    <img src={fc.imageUrl} alt={fc.label} loading="lazy" className="block max-h-[400px] object-contain" />
                  ) : fc.mermaid ? (
                    <pre className="bg-surface-container-low border border-outline-variant rounded p-2 font-mono text-label overflow-x-auto whitespace-pre">{fc.mermaid}</pre>
                  ) : null}
                </div>
              ))}
            </td>
          </tr>
          <tr className="border-b border-outline-variant/60">
            <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Risk</td>
            <td className="px-4 py-3">{data.risk}</td>
          </tr>
          <tr className="border-b border-outline-variant/60">
            <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Capacity(Density)</td>
            <td className="px-4 py-3">{data.capacity}</td>
          </tr>
          <tr className="border-b border-outline-variant/60">
            <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Input Name</td>
            <td className="px-4 py-3">{data.inputName}</td>
          </tr>
          <tr>
            <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Output Name</td>
            <td className="px-4 py-3">{data.outputName}</td>
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
      <div className="overflow-hidden border border-outline-variant rounded-lg">
        <table className="w-full text-left text-body">
          <tbody>
            <tr className="border-b border-outline-variant/60">
              <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container align-top w-40">Requirements</td>
              <td className="px-4 py-3">
                {data.descriptionList.length > 0 ? (
                  <div>
                    <p className="font-semibold text-on-surface mb-1">Behavior Description</p>
                    {data.descriptionList.map((item, i) => (
                      <p key={i} className="text-on-surface">• {item}</p>
                    ))}
                  </div>
                ) : <span className="text-on-surface-variant">-</span>}
              </td>
            </tr>
            <tr className="border-b border-outline-variant/60">
              <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Risk</td>
              <td className="px-4 py-3">{data.risk}</td>
            </tr>
            <tr className="border-b border-outline-variant/60">
              <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Capacity</td>
              <td className="px-4 py-3">{data.capacity}</td>
            </tr>
            <tr className="border-b border-outline-variant/60">
              <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Input Name</td>
              <td className="px-4 py-3">{data.inputName}</td>
            </tr>
            <tr>
              <td className="px-4 py-3 font-semibold text-on-surface-variant bg-surface-container">Output Name</td>
              <td className="px-4 py-3">{data.outputName}</td>
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

/* ── One rich section (richtext | table | diagram | flowchart_table | behavior_table) + nested children ── */
function RichSectionView({ section, depth = 0 }: { section: RichSection; depth?: number }) {
  const headingSize = depth === 0 ? 'text-[20px]' : depth === 1 ? 'text-[17px]' : 'text-[15px]'
  return (
    <section id={`sec-${section.id}`} className="scroll-mt-6">
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
        <p className="text-[15px] text-on-surface leading-relaxed whitespace-pre-line">{section.content}</p>
      ) : null}
      {section.children.length > 0 && (
        <div className="mt-8 space-y-8 pl-4 border-l border-outline-variant">
          {section.children.map((c) => <RichSectionView key={c.id} section={c} depth={depth + 1} />)}
        </div>
      )}
    </section>
  )
}

/* ── Review tracker (in-review right panel) ── */
function ReviewTracker({
  sections, progress, reviewer, reviewerInitials, isAdmin, assignedToMe,
  onMarkComplete, onReassign, onAssignToMe, onJump,
}: {
  sections: DocSection[]
  progress?: { resolved: number; total: number }
  reviewer?: string
  reviewerInitials?: string
  isAdmin: boolean
  assignedToMe: boolean
  onMarkComplete: () => void
  onReassign: () => void
  onAssignToMe: () => void
  onJump: (key: string) => void
}) {
  const total = progress?.total ?? sections.length
  const resolved = progress?.resolved ?? 0
  const pct = total ? Math.round((resolved / total) * 100) : 0

  return (
    <div className="flex-1 overflow-y-auto py-3 px-3 space-y-4">
      {/* Reviewer + progress */}
      <div>
        <Text variant="label" className="block text-on-surface-variant tracking-[0.08em] mb-2">Reviewer</Text>
        <div className="flex items-center gap-2 mb-2">
          <div className="w-7 h-7 rounded-full bg-secondary-container flex items-center justify-center flex-shrink-0">
            <span className="font-bold text-on-secondary-container font-sans text-micro">{reviewerInitials ?? '—'}</span>
          </div>
          <span className="font-mono text-caption text-on-surface truncate">{reviewer ?? 'Unassigned'}</span>
        </div>
        <div className="flex items-center justify-between mb-1">
          <Text variant="caption" className="font-mono">Progress</Text>
          <Text variant="caption" className="font-mono">{pct}%</Text>
        </div>
        <div className="h-1.5 rounded-[3px] bg-surface-container overflow-hidden">
          {/* eslint-disable-next-line no-restricted-syntax -- review progress width is data-driven */}
          <div className={cn('h-full rounded-[3px]', pct === 100 ? 'bg-[#00a572]' : 'bg-secondary')} style={{ width: `${pct}%` }} />
        </div>
        <Text as="p" variant="caption" className="font-mono mt-1">{resolved} of {total} sections</Text>
      </div>

      {/* Section checklist */}
      <div>
        <Text variant="label" className="block text-on-surface-variant tracking-[0.08em] mb-2">Sections</Text>
        <div className="space-y-1.5">
          {sections.map((s) => {
            const st = sectionStateIcon(s.reviewState)
            return (
              <button
                key={s.key}
                onClick={() => onJump(s.key)}
                className="w-full flex items-center gap-1.5 text-left hover:bg-surface-container-low rounded transition-colors px-1 py-0.5"
              >
                <Icon name={st.icon} size={12} className={st.cls} />
                <span className="font-mono text-label text-on-surface-variant truncate">{s.title}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Actions */}
      <div className="space-y-2 pt-1 border-t border-outline-variant">
        <button
          onClick={onMarkComplete}
          className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 bg-[#00a572] text-white rounded-lg hover:opacity-90 transition-opacity font-mono text-label font-semibold"
        >
          <Icon name="check_circle" size={12} />
          Mark Complete
        </button>
        {isAdmin && (
          <button
            onClick={onReassign}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 border border-outline-variant hover:bg-surface-container rounded-lg transition-colors font-mono text-label text-on-surface-variant"
          >
            <Icon name="person_add" size={12} />
            Re-assign
          </button>
        )}
        {!isAdmin && !assignedToMe && (
          <button
            onClick={onAssignToMe}
            className="w-full flex items-center justify-center gap-1.5 px-2 py-1.5 border border-secondary text-secondary hover:bg-surface-container-low rounded-lg transition-colors font-mono text-label font-semibold"
          >
            <Icon name="person_add" size={12} />
            Assign to me
          </button>
        )}
      </div>
    </div>
  )
}

/* ── Assign reviewers slide-in panel ── */
function AssignReviewersPanel({
  members, refLabel, shortSha, busy, onClose, onAssign,
}: {
  members: TeamMember[]
  refLabel: string
  shortSha?: string
  busy: boolean
  onClose: () => void
  onAssign: (userId: string) => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const selectedMember = members.find((m) => (m.userId ?? m.id) === selected)

  return (
    <div className="absolute right-0 top-0 bottom-0 w-[320px] bg-white border-l border-outline-variant flex flex-col z-30 shadow-[-4px_0_20px_rgba(4,22,39,.08)]">
      <div className="flex-shrink-0 px-4 py-3 border-b border-outline-variant flex items-center justify-between">
        <div>
          <Text as="p" variant="mono" className="text-on-surface">Assign Reviewers</Text>
          <Text as="p" variant="caption" className="font-mono mt-0.5">{refLabel}{shortSha ? ` · ${shortSha}` : ''}</Text>
        </div>
        <button onClick={onClose} className="p-1 hover:bg-surface-container rounded-lg transition-colors">
          <Icon name="close" size={18} className="text-on-surface-variant" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-4 py-4">
        <Text variant="label" className="block text-on-surface-variant tracking-[0.08em] mb-2">Select reviewer</Text>
        <div className="space-y-1">
          {members.length === 0 && (
            <Text as="p" variant="caption" className="font-mono">No team members to assign.</Text>
          )}
          {members.map((m) => {
            const uid = m.userId ?? m.id
            const active = selected === uid
            return (
              <button
                key={m.id}
                onClick={() => setSelected(uid)}
                className={cn(
                  'w-full flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-colors text-left',
                  active ? 'border-secondary bg-surface-container-low' : 'border-outline-variant hover:border-secondary hover:bg-surface-container-low',
                )}
              >
                <div
                  className="w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0"
                  // eslint-disable-next-line no-restricted-syntax -- member avatar colour is data-driven
                  style={{ background: m.avatarColor }}
                >
                  {/* eslint-disable-next-line no-restricted-syntax -- member avatar text colour is data-driven */}
                  <span className="font-bold font-sans text-micro" style={{ color: m.avatarTextColor }}>{m.initials}</span>
                </div>
                <span className="flex-1 font-mono text-caption text-on-surface truncate">{m.name}</span>
                {active && <Icon name="check" size={16} className="text-secondary flex-shrink-0" />}
              </button>
            )
          })}
        </div>
        <Text as="p" variant="caption" className="font-mono mt-3">
          {selectedMember ? `Selected: ${selectedMember.name}` : 'No reviewer selected'}
        </Text>
      </div>

      <div className="flex-shrink-0 px-4 py-3 border-t border-outline-variant">
        <button
          disabled={!selected || busy}
          onClick={() => selected && onAssign(selected)}
          className="w-full flex items-center justify-center gap-2 px-4 py-2.5 bg-secondary text-white hover:bg-secondary-container rounded-xl transition-colors font-mono text-caption font-medium disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <Icon name="send" size={16} />
          Send for Review
        </button>
      </div>
    </div>
  )
}
