import { useMemo, useState } from 'react'
import { useJobFunctions } from '../../../hooks/useJobs'
import { useClaimDocument, useReviewEvents } from '../../../hooks/useApproval'
import { Icon, Text } from '../../../components/ui'
import { AssignReviewerDialog } from '../../../components/review/AssignReviewerDialog'
import { cn } from '../../../lib/cn'
import type { AnalysisJob, Document, Project, TeamMember, Version } from '../../../types'
import { TeamRow } from './ConfigOverview'
import {
  AdminDocsCard, ClaimPoolCard, KpiStrip, LastActionsCard, MyReviewsCard, ReviewQueueCard,
} from './ReviewCards'

/* ════════════ Generated-state content (matches project-detail.html) ════════════ */

type Nav = (to: string) => void

function TeamCard({ team, teamLoading, go, projectId }: { team?: TeamMember[]; teamLoading: boolean; go: Nav; projectId: string }) {
  return (
    <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <Text as="h2" variant="heading" className="text-on-surface">Team</Text>
        <button onClick={() => go(`/projects/${projectId}/team`)} className="flex items-center gap-1 px-2.5 py-1.5 border border-outline-variant hover:bg-surface-container text-on-surface-variant rounded-lg transition-colors font-mono text-caption font-medium">
          <Icon name="person_add" size={14} />Add
        </button>
      </div>
      {teamLoading ? (
        <div className="divide-y divide-outline-variant">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="flex items-center gap-3 px-4 py-2.5">
              <div className="w-7 h-7 rounded-full bg-surface-container animate-pulse flex-shrink-0" />
              <div className="flex-1 h-3 bg-surface-container animate-pulse rounded" />
            </div>
          ))}
        </div>
      ) : (
        <div className="divide-y divide-outline-variant">{team?.map((m) => <TeamRow key={m.id} member={m} />)}</div>
      )}
    </div>
  )
}

function FunctionVisibilityCard({ projectId, job, latestVersion }: { projectId: string; job?: AnalysisJob | null; latestVersion: string }) {
  // Counts from the latest finished run's function list (`GET …/jobs/{id}/functions`). There is
  // no editor to hide functions yet, so Manage is shown as unavailable rather than doing nothing.
  const finished = job?.status === 'complete' ? job : undefined
  const { data, isLoading } = useJobFunctions(projectId, finished?.id)
  const summary = data?.summary
  return (
    <div className="bg-surface-container-lowest border border-outline-variant rounded-xl overflow-hidden">
      <div className="px-4 py-3.5 border-b border-outline-variant flex items-center justify-between">
        <div>
          <Text as="h2" variant="heading" className="text-on-surface">Function Visibility</Text>
          <Text as="p" variant="caption" className="font-mono mt-0.5">
            {summary
              ? `${summary.hidden} of ${summary.total} functions hidden from DOCX`
              : finished && isLoading ? 'Loading…' : 'No finished run to count yet'}
          </Text>
        </div>
        <button
          disabled
          title="Not available yet — there is no editor to hide functions"
          className="flex items-center gap-1 px-3 py-1.5 border border-outline-variant rounded-lg text-secondary font-mono text-caption opacity-50 cursor-not-allowed"
        >
          Manage<Icon name="arrow_forward" size={14} />
        </button>
      </div>
      <div className="px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <Icon name={summary?.hidden ? 'visibility_off' : 'visibility'} size={14} className={summary?.hidden ? 'text-warn' : 'text-on-surface-variant'} />
          <span className={cn('font-mono text-xs', summary?.hidden ? 'text-warn' : 'text-on-surface-variant')}>{summary ? `${summary.hidden} hidden` : '—'}</span>
        </div>
        <span className="text-on-surface-variant font-mono text-caption">Last: {latestVersion}</span>
      </div>
    </div>
  )
}

export function GeneratedContent({ project, documents, version, team, versions, job, isAdmin, projectId, go, meId, teamLoading }: {
  project: Project; documents?: Document[]; version?: Version; team?: TeamMember[]; versions?: Version[]; job?: AnalysisJob | null
  isAdmin: boolean; projectId: string; go: Nav; meId: string; teamLoading: boolean
}) {
  const docs = useMemo(() => documents ?? [], [documents])
  const latestVersion = project.latestVersion ?? versions?.[0]?.tag ?? 'v1.0.0'
  const claim = useClaimDocument(projectId)
  const { data: events, isLoading: eventsLoading } = useReviewEvents(projectId, version?.id)
  const names = useMemo(() => new Map((team ?? []).map((m) => [m.userId ?? m.id, m.name])), [team])
  const nameOf = (id: string) => names.get(id)
  const [assignFor, setAssignFor] = useState<Document | null>(null)
  return (
    <>
      <KpiStrip documents={docs} version={version} versions={versions} team={team} isAdmin={isAdmin} meId={meId} />
      <div className="flex gap-6 mb-8 items-stretch">
        <div className="flex-1 min-w-0 flex flex-col gap-4">
          {isAdmin
            ? <AdminDocsCard documents={docs} go={go} projectId={projectId} />
            : <MyReviewsCard documents={docs} meId={meId} go={go} projectId={projectId} />}
          {!isAdmin && <ClaimPoolCard documents={docs} onClaim={(id) => claim.mutate(id)} claiming={claim.isPending} />}
          {isAdmin && <TeamCard team={team} teamLoading={teamLoading} go={go} projectId={projectId} />}
        </div>
        <div className="w-[300px] flex-shrink-0 flex flex-col gap-4">
          {isAdmin && <ReviewQueueCard documents={docs} go={go} projectId={projectId} onAssign={setAssignFor} />}
          <FunctionVisibilityCard projectId={projectId} job={job} latestVersion={latestVersion} />
          <LastActionsCard
            events={events}
            documents={docs}
            versions={versions}
            isAdmin={isAdmin}
            meId={meId}
            nameOf={nameOf}
            isLoading={eventsLoading}
          />
        </div>
      </div>
      {assignFor && (
        <AssignReviewerDialog projectId={projectId} documents={[assignFor]} allDocuments={docs} onClose={() => setAssignFor(null)} />
      )}
    </>
  )
}
