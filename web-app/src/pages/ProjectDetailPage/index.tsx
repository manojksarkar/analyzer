import { Fragment, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useProject, useDocuments, useTeam, useCommits, useVersions } from '../../hooks/useProjects'
import { useCurrentJob, useStartJob, useCancelJob, useJobEvents } from '../../hooks/useJobs'
import { useProjectViewState } from '../../hooks/useProjectViewState'
import { DashboardSkeleton, Icon, Text } from '../../components/ui'
import { SubbarCta } from '../../components/shell/SubbarCta'
import { cn } from '../../lib/cn'
import { useAuthStore } from '../../store/auth'
import type { StartJobInput } from '../../services/api'
import { ConfigOverview } from './components/ConfigOverview'
import { FailedRunBanner, RunWarningsBanner } from './components/RunBanners'
import { RunAnalysisModal } from './components/RunAnalysisModal'
import { GeneratedContent } from './components/GeneratedContent'
import { PHASE_UI, fmtClock, fmtEta, fmtStart, phaseTime } from './helpers'

/* ─── Phase step (running panel) ─── */
type PhaseStatus = 'done' | 'active' | 'pending'
function PhaseStep({ n, label, status, time }: { n: number; label: string; status: PhaseStatus; time: string }) {
  const timeColor = status === 'done' ? 'text-[#00a572]' : status === 'active' ? 'text-secondary' : 'text-outline-variant'
  return (
    <div className="flex flex-col items-center text-center min-w-[105px]">
      <div
        className={cn(
          'w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0',
          status === 'done' ? 'bg-[#00a572]' : status === 'active' ? 'bg-secondary' : 'bg-surface-container',
        )}
      >
        {status === 'done' ? (
          <Icon name="check" size={14} fill className="text-white" />
        ) : status === 'active' ? (
          <div className="animate-spin w-3.5 h-3.5 rounded-full border-2 border-white/35 border-t-white" />
        ) : (
          <span className="text-body font-semibold text-outline">{n}</span>
        )}
      </div>
      <p className={cn('mt-1.5 font-semibold text-body', status === 'pending' ? 'text-outline' : 'text-on-surface')}>{label}</p>
      <p className={cn('mt-0.5 text-label font-mono', timeColor)}>{time}</p>
    </div>
  )
}

export function ProjectDetailPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()

  const meId = useAuthStore((s) => s.user?.id ?? '')

  const { data: project } = useProject(projectId ?? '')
  // pageState + the version to view come from the Subbar selection (shared store).
  const { pageState, isLoading, viewVersion, viewVersionId, selectedCommit } = useProjectViewState(projectId ?? '')
  const { data: versions } = useVersions(projectId ?? '')
  // While a run is going, the Overview still shows the last finished version under the run card
  // (the picked one, when it is finished). It used to hide every document until the run ended.
  const running = pageState === 'running'
  const doneVersion = running
    ? (viewVersion && viewVersion.status !== 'draft' ? viewVersion : versions?.find((v) => v.status !== 'draft'))
    : undefined
  const contentVersionId = running ? doneVersion?.id : viewVersionId
  const { data: documents, isLoading: documentsLoading } = useDocuments(projectId ?? '', contentVersionId ? { versionId: contentVersionId } : undefined)
  const { data: team, isLoading: teamLoading } = useTeam(projectId ?? '')
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId ?? '')
  const { data: job } = useCurrentJob(projectId ?? '')
  const startJob = useStartJob(projectId ?? '')
  const cancelJob = useCancelJob(projectId ?? '')
  const [runOpen, setRunOpen] = useState(false)
  useJobEvents(projectId ?? '', job?.id, job?.status)

  // Role is per-project (API's my_role → project.userRole).
  const isAdmin = project?.userRole === 'admin'

  // The commit shown in the empty/run states: the picker selection, else latest.
  const shownCommit = selectedCommit ?? commits?.[0]
  const startAnalysis = (body: StartJobInput) =>
    startJob.mutate(body, { onSuccess: () => setRunOpen(false) })

  const showContent = ['in_review', 'complete', 'stale'].includes(pageState) || (running && !!doneVersion)

  return (
    <div className="flex-1 overflow-y-auto bg-background">
      {/* The page's Subbar action. Without it a project that has a version had no way to start
          its next run: the only other buttons are on the empty state and the failure banner. */}
      {isAdmin && !isLoading && pageState !== 'running' && (
        <SubbarCta>
          <button
            onClick={() => setRunOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors font-mono text-caption font-bold tracking-[0.04em]"
          >
            <Icon name="play_circle" size={14} fill />
            RUN ANALYSIS
          </button>
        </SubbarCta>
      )}
      <div className="px-6 py-6 max-w-[1280px] mx-auto">

        {/* ══ LOADING — gate the empty-state flash until the view state resolves ══ */}
        {isLoading && !project ? (
          <DashboardSkeleton />
        ) : (
          <>

        {/* ══ LAST RUN FAILED — the error, which no other state shows ══ */}
        {job?.status === 'failed' && pageState !== 'running' && (
          <FailedRunBanner job={job} isAdmin={isAdmin} onRerun={() => setRunOpen(true)} />
        )}

        {/* ══ THE RUN FINISHED, WITH WARNINGS — e.g. a component path the checkout did not have ══ */}
        {viewVersion && viewVersion.warnings.length > 0 && pageState !== 'running' && (
          <RunWarningsBanner key={viewVersion.id} version={viewVersion} />
        )}

        {/* ══ EMPTY STATE (not yet analysed) ══ */}
        {pageState === 'never' && (
          <>
            <div className="mb-6 rounded-xl border border-outline-variant bg-white px-8 py-10 flex flex-col items-center text-center gap-5">
              <div className="w-14 h-14 rounded-full bg-surface-container-low border border-outline-variant flex items-center justify-center">
                <Icon name="auto_awesome" size={28} className="text-on-surface-variant" />
              </div>
              <div>
                <Text as="h3" variant="heading" className="text-on-surface">No documents generated yet</Text>
                <p className="text-on-surface-variant mt-2 font-mono text-caption max-w-[340px]">
                  Run analysis on <strong>{shownCommit ? `${shownCommit.branch} @ ${shownCommit.shortSha}` : 'the latest commit'}</strong> to generate each component's Detailed Design (SWE.3) and Unit Test Specification (SWE.4).
                </p>
              </div>
              <button
                onClick={() => setRunOpen(true)}
                disabled={!isAdmin}
                className="flex items-center gap-2 px-5 py-2.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-xl transition-colors disabled:opacity-60 font-mono text-xs font-bold tracking-[0.04em]"
              >
                <Icon name="play_circle" size={16} fill />
                RUN ANALYSIS
              </button>
            </div>

            {/* Show the captured project configuration even before analysis runs. */}
            {project && <ConfigOverview project={project} team={team} teamLoading={teamLoading} />}
          </>
        )}

        {/* ══ RUNNING STATE ══ */}
        {pageState === 'running' && job && (
          <div className="mb-7 rounded-xl overflow-hidden border border-outline-variant">
            {/* Dark header */}
            <div className="px-5 py-4 flex items-center justify-between bg-primary">
              <div className="flex items-center gap-3">
                {/* A queued job waits for a free worker: it must not look like it is running. */}
                <div className="w-8 h-8 rounded-full flex items-center justify-center flex-shrink-0 border-2 border-secondary border-t-transparent">
                  {job.status === 'queued'
                    ? <Icon name="hourglass_empty" size={16} className="text-on-primary-container" />
                    : <div className="animate-spin w-full h-full rounded-full border-2 border-secondary border-t-transparent" />}
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <p className="text-white font-semibold font-sans text-sm">
                      Analysis {job.status === 'paused' ? 'Paused' : job.status === 'queued' ? 'Queued' : 'Running'}
                    </p>
                    <span className={cn('font-mono text-micro font-bold text-white px-[7px] py-px rounded-[3px] uppercase tracking-[0.05em]', job.status === 'queued' ? 'bg-outline' : 'bg-secondary')}>
                      {job.status === 'queued' ? 'Queued' : 'Live'}
                    </span>
                  </div>
                  {(() => {
                    // Show the version being generated by default; fall back to
                    // branch @ commit only when a specific (non-latest) commit was chosen.
                    const onLatest = !commits?.[0] || job.commitSha === commits[0].sha
                    const showVersion = onLatest && !!job.versionTag
                    return (
                      <div className="flex items-center gap-2 mt-0.5 text-on-primary-container">
                        {showVersion ? (
                          <>
                            <Icon name="sell" size={12} />
                            <p className="text-caption font-mono">Version <span className="text-[#4d9fff]">{job.versionTag}</span></p>
                          </>
                        ) : (
                          <>
                            <Icon name="source" size={12} />
                            <p className="text-caption font-mono">Branch <span className="text-[#4d9fff]">{job.branch}</span></p>
                            <span className="text-[#1e3045]">·</span>
                            <p className="text-caption font-mono">Commit <span className="text-[#4d9fff]">{job.shortSha}</span></p>
                          </>
                        )}
                      </div>
                    )
                  })()}
                </div>
              </div>
              <div className="flex items-center gap-5">
                <div className="text-right">
                  <p className="text-label font-mono text-outline uppercase tracking-[0.08em]">Started</p>
                  <p className="font-mono text-xs text-on-primary-container">{fmtStart(job.startedAt)}</p>
                </div>
                <div className="text-right">
                  <p className="text-label font-mono text-outline uppercase tracking-[0.08em]">Elapsed</p>
                  <p className="font-mono text-xs text-white">{fmtClock(job.elapsedSeconds)}</p>
                </div>
                {isAdmin && (
                  <button
                    onClick={() => cancelJob.mutate(job.id)}
                    disabled={cancelJob.isPending}
                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg transition-colors disabled:opacity-60 border border-[#4d2020] text-[#ff7070] font-mono text-caption font-medium"
                  >
                    <Icon name="stop_circle" size={14} />
                    Cancel Job
                  </button>
                )}
              </div>
            </div>

            {/* Phase steps (driven by the live job) */}
            <div className="bg-white px-6 pt-5 pb-3">
              <div className="flex items-start">
                {job.phases.map((p, i) => (
                  <Fragment key={p.number}>
                    {i > 0 && (
                      <div className={cn('flex-1 h-0.5 rounded-full mt-3.5 mx-1.5', p.status !== 'pending' ? 'bg-[#00a572]' : 'bg-surface-container')} />
                    )}
                    <PhaseStep n={p.number} label={p.name} status={PHASE_UI[p.status]} time={phaseTime(p)} />
                  </Fragment>
                ))}
              </div>
            </div>

            {/* Activity row */}
            <div className="bg-white px-6 pb-5">
              <div className="bg-surface-container-low border border-outline-variant rounded-lg px-4 py-3">
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-2">
                    <Icon name={job.status === 'queued' ? 'hourglass_empty' : 'psychology'} size={14} className="text-secondary" />
                    <p className="text-on-surface font-mono text-caption">{job.currentActivity}</p>
                  </div>
                  <span className="text-secondary font-mono text-xs font-medium">{job.phasePct}%</span>
                </div>
                {/* No detail and no estimate: no row (it showed a lone "—"). */}
                {(() => {
                  const hasRow = !!job.activityDetail || job.etaSeconds != null
                  return (
                    <>
                      <div className={cn('progress-track', hasRow && 'mb-2')}>
                        {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
                        <div className="progress-fill bg-secondary" style={{ width: `${job.phasePct}%` }} />
                      </div>
                      {hasRow && (
                        <div className="flex items-center justify-between gap-4">
                          <p className="text-on-surface-variant font-mono text-caption truncate">{job.activityDetail}</p>
                          {job.etaSeconds != null && (
                            <p className="text-outline font-mono text-caption flex-shrink-0">Est. ~{fmtEta(job.etaSeconds)} remaining</p>
                          )}
                        </div>
                      )}
                    </>
                  )
                })()}
              </div>
              <div className="flex items-center gap-2 mt-2 px-1">
                <Icon name="info" size={13} className="text-on-surface-variant" />
                <p className="text-on-surface-variant font-mono text-caption">Job runs on the server — switch branches or close this tab safely. Return any time to check progress.</p>
              </div>
            </div>
          </div>
        )}

        {/* ══ STALE BANNER ══ */}
        {pageState === 'stale' && (
          <div className="mb-6 flex items-center gap-3 px-5 py-3.5 rounded-xl bg-[#fffbeb] border border-amber">
            <Icon name="warning" size={20} fill className="flex-shrink-0 text-[#d97706]" />
            <div className="flex-1 min-w-0">
              <p className="font-semibold text-on-surface text-body">3 new commits since this analysis</p>
              <p className="text-caption text-outline font-mono mt-0.5">Results may be outdated — re-run to analyze the latest code.</p>
            </div>
            <button
              onClick={() => setRunOpen(true)}
              disabled={!isAdmin}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-secondary hover:bg-secondary-container text-on-secondary rounded-lg transition-colors flex-shrink-0 disabled:opacity-60 font-mono text-caption font-bold tracking-[0.04em]"
            >
              <Icon name="play_circle" size={14} fill />
              Re-run
            </button>
          </div>
        )}

        {/* ══ GENERATED CONTENT — KPI strip + docs + sidebar (matches project-detail.html) ══ */}
        {running && doneVersion && project && (
          <p className="mb-3 flex items-center gap-1.5 font-mono text-caption text-on-surface-variant">
            <Icon name="history" size={14} />
            Showing <span className="text-on-surface font-semibold">{doneVersion.tag}</span>
            {job?.versionTag ? <> while <span className="text-secondary">{job.versionTag}</span> is being generated</> : null}
          </p>
        )}
        {showContent && project && (
          documentsLoading && !documents ? (
            <DashboardSkeleton />
          ) : (
            <GeneratedContent
              project={project}
              documents={documents}
              version={running ? doneVersion : viewVersion}
              team={team}
              versions={versions}
              job={job}
              isAdmin={isAdmin}
              projectId={projectId ?? ''}
              go={(to) => navigate(to)}
              meId={meId}
              teamLoading={teamLoading}
            />
          )
        )}

          </>
        )}

      </div>

      {runOpen && project && (
        <RunAnalysisModal
          project={project}
          commits={commits}
          commitsLoading={commitsLoading}
          versions={versions}
          submitting={startJob.isPending}
          defaultSha={shownCommit?.sha}
          onClose={() => setRunOpen(false)}
          onStart={startAnalysis}
        />
      )}
    </div>
  )
}
