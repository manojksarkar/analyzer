import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useProject, useVersions, useCommits, projectKeys } from './useProjects'
import { useCurrentJob } from './useJobs'
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

const ACTIVE_JOB = ['queued', 'running', 'paused']
const ENDED_JOB = ['complete', 'failed', 'cancelled']

/**
 * When a run ends while the project is open, read the project again — every key of it (project,
 * versions, commits, documents, components, review) — so every page leaves the "running" / empty
 * state by itself. Only on the change from at work to ended, seen here: a page opened after the
 * run ended reads nothing again (each visit used to refetch the whole project, the last run
 * being "complete"). Called once, by the project layout, so one run's end is one refresh.
 * (`jobs/current` skips a cancelled job — it answers with the run before it — so a cancel mostly
 * shows up as that run's status; useCancelJob refetches the project itself.)
 */
export function useRefreshOnJobEnd(projectId: string): void {
  const { data: job } = useCurrentJob(projectId)
  const qc = useQueryClient()
  const jobStatus = job?.status
  const seen = useRef(jobStatus)
  useEffect(() => {
    const was = seen.current
    seen.current = jobStatus
    if (!projectId || !was || !jobStatus || !ACTIVE_JOB.includes(was) || !ENDED_JOB.includes(jobStatus)) return
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
  }, [jobStatus, projectId, qc])
}
