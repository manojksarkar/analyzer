import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useProject, useVersions, useCommits, projectKeys } from './useProjects'
import { useCurrentJob } from './useJobs'
import { useProjectRuns } from './useVersionComponents'
import { useUIStore, type Selection } from '../store/ui'
import { liveSelection } from '../lib/selection'
import type { PageState, Version, Commit } from '../types'

/** The Subbar's pick for the project; one naming a version that is gone counts as none
 *  (lib/selection `liveSelection`). Shared by the view state and the picker itself. */
export function usePickerSelection(projectId: string): Selection | undefined {
  const { data: versions } = useVersions(projectId)
  const selection = useUIStore((s) => (projectId ? s.selectedRef[projectId] : undefined))
  return liveSelection(selection, versions)
}

/**
 * Resolves the project's *displayed* state from the Subbar's commit/version
 * selection (shared via the UI store), so both the detail page and the subbar
 * status badge react to the picker.
 *
 *  - No selection → latest version (default), state from the project.
 *  - A version selected → that version's state + its docs. A version that is gone (a cancelled
 *    run's draft) is no selection → the default.
 *  - A commit selected → that commit's state (e.g. a "Not Run" commit → the
 *    empty view); if the commit is tagged, its version's docs.
 *  - An active job always wins (→ "running").
 *
 * All the underlying queries are shared via React Query, so calling this in
 * several components does not refetch.
 */
export function useProjectViewState(projectId: string): {
  pageState: PageState
  isLoading: boolean
  viewVersion?: Version
  viewVersionId?: string
  selectedCommit?: Commit
} {
  const { data: project, isLoading: projectLoading } = useProject(projectId)
  const { data: versions, isLoading: versionsLoading } = useVersions(projectId)
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId)
  const { data: job, isLoading: jobLoading } = useCurrentJob(projectId)
  const selection = usePickerSelection(projectId)

  // First-load only (isLoading, not isFetching) so background refetches don't
  // re-trigger skeletons. Consumers gate their empty states on this so the
  // default `pageState = 'never'` isn't shown before the queries resolve. The commits (every
  // page of them) count only for a commit pick: nothing else here reads them.
  const isLoading = projectLoading || versionsLoading || jobLoading || (selection?.type === 'commit' && commitsLoading)

  // Resolve the selection: a version by its id (so two versions on the same
  // commit don't collide), a commit by sha.
  const selVersion = selection?.type === 'version'
    ? versions?.find((v) => v.id === selection.id)
    : undefined
  const selCommit = selection?.type === 'commit'
    ? commits?.find((c) => c.sha === selection.sha)
    : undefined
  const selCommitVersion = selCommit?.versionTag
    ? versions?.find((v) => v.tag === selCommit.versionTag)
    : undefined
  // The version whose documents we show; default to the latest when nothing is
  // explicitly selected. A "Not Run" commit has no version → undefined.
  const viewVersion = selVersion ?? selCommitVersion ?? (selection ? undefined : versions?.[0])

  const jobActive = !!job && ['queued', 'running', 'paused'].includes(job.status)
  let base: PageState = project?.pageState ?? 'never'
  if (selection) {
    if (viewVersion) base = viewVersion.pageState
    else if (selCommit) base = selCommit.pageState
  }
  const pageState: PageState = jobActive ? 'running' : base

  return { pageState, isLoading, viewVersion, viewVersionId: viewVersion?.id, selectedCommit: selCommit }
}

/**
 * A page opened on a document — a link from the list, a notification, an address typed or
 * shared — shows that document's version: the Subbar's pick becomes it, so the version chip, the
 * status pill and Compare's current side are the document's, not the latest version's. Once per
 * document opened: a pick made in the Subbar afterwards stands. Nothing is picked when the
 * version shown already is the document's (no pick is made for the latest version).
 *
 * `following`: the pick is about to change (until it has, a page reading by the shown version
 * would read the wrong one — Compare holds its reads).
 */
export function useFollowDocumentVersion(
  projectId: string, doc: { id: string; versionId?: string } | undefined,
): { following: boolean } {
  const { viewVersionId, isLoading } = useProjectViewState(projectId)
  const selection = useUIStore((s) => (projectId ? s.selectedRef[projectId] : undefined))
  const setSelectedRef = useUIStore((s) => s.setSelectedRef)
  const target = doc?.versionId
  const key = target && doc ? `${projectId}|${doc.id}` : null
  // The pick as it was when this document opened: once it has changed — by the follow below, or
  // by a pick in the Subbar — this document's follow is done.
  const [opened, setOpened] = useState<{ key: string | null; selection: typeof selection }>({ key, selection })
  if (opened.key !== key) setOpened({ key, selection })
  const following = !!key && !!target && !isLoading && viewVersionId !== target
    && opened.key === key && selection === opened.selection
  useEffect(() => {
    if (following && target) setSelectedRef(projectId, { type: 'version', id: target })
  }, [following, projectId, target, setSelectedRef])
  return { following }
}

const ACTIVE_JOB = ['queued', 'running', 'paused']
const ENDED_JOB = ['complete', 'failed', 'cancelled']
const active = (status: string | undefined) => !!status && ACTIVE_JOB.includes(status)
const ended = (status: string | undefined) => !!status && ENDED_JOB.includes(status)

interface Seen {
  projectId: string
  /** undefined: not read yet; null: the project has no job. */
  jobId: string | null | undefined
  jobStatus: string | undefined
  /** Runs alive (`useProjectRuns`); undefined: not read (or an API without them). */
  alive: number | undefined
  /** When the runs were read. */
  runsAt: number
}

/**
 * When a run ends while the project is open, read the project again — every key of it (project,
 * versions, commits, documents, components, review) — so every page leaves the "running" / empty
 * state by itself. Only on a change seen here: a page opened after the run ended reads nothing
 * again (each visit used to refetch the whole project, the last run being "complete"). Called
 * once, by the project layout, so one run's end is one refresh.
 *
 * A run has ended when: the web job at work (`jobs/current`) ends, is replaced by another, or is
 * gone; a job not seen before is already over (it started and ended between two reads); or fewer
 * runs are alive (`/runs` — `analyzer.py … --detach` on the server, which `jobs/current` never
 * shows). A drop in the runs that a refresh of this hook already read is not refreshed twice.
 * What was seen belongs to one project: another project's says nothing of this one.
 * (`jobs/current` skips a cancelled job — it answers with the run before it — which is a job
 * replaced; useCancelJob refetches the project itself too.)
 */
export function useRefreshOnJobEnd(projectId: string): void {
  const { data: job } = useCurrentJob(projectId)
  const { data: runs, dataUpdatedAt: runsAt } = useProjectRuns(projectId)
  const qc = useQueryClient()
  const jobId = job === undefined ? undefined : job?.id ?? null
  const jobStatus = job?.status
  const alive = runs?.filter((r) => r.alive).length
  const seen = useRef<Seen | null>(null)
  const refreshedAt = useRef(0)
  useEffect(() => {
    const was = seen.current
    seen.current = { projectId, jobId, jobStatus, alive, runsAt }
    if (!projectId || !was || was.projectId !== projectId) return
    const jobKnown = was.jobId !== undefined && jobId !== undefined
    const jobEnded = jobKnown && (
      (active(was.jobStatus) && (jobId !== was.jobId || !active(jobStatus)))
      || (jobId !== null && jobId !== was.jobId && ended(jobStatus))
    )
    // The runs read with a refresh of ours were read with the project: their drop is in it.
    const runEnded = was.alive !== undefined && alive !== undefined && alive < was.alive
      && refreshedAt.current < was.runsAt
    if (!jobEnded && !runEnded) return
    refreshedAt.current = Date.now()
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
  }, [projectId, jobId, jobStatus, alive, runsAt, qc])
}
