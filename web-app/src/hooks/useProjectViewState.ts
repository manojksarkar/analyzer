import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useProject, useVersions, useCommits, projectKeys } from './useProjects'
import { useCurrentJob } from './useJobs'
import { useUIStore } from '../store/ui'
import type { PageState, Version, Commit } from '../types'

/**
 * Resolves the project's *displayed* state from the Subbar's commit/version
 * selection (shared via the UI store), so both the detail page and the subbar
 * status badge react to the picker.
 *
 *  - No selection → latest version (default), state from the project.
 *  - A version selected → that version's state + its docs.
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
  selectedSha?: string
} {
  const { data: project, isLoading: projectLoading } = useProject(projectId)
  const { data: versions, isLoading: versionsLoading } = useVersions(projectId)
  const { data: commits, isLoading: commitsLoading } = useCommits(projectId)
  const { data: job, isLoading: jobLoading } = useCurrentJob(projectId)
  const selection = useUIStore((s) => (projectId ? s.selectedRef[projectId] : undefined))

  // First-load only (isLoading, not isFetching) so background refetches don't
  // re-trigger skeletons. Consumers gate their empty states on this so the
  // default `pageState = 'never'` isn't shown before the queries resolve.
  const isLoading = projectLoading || versionsLoading || commitsLoading || jobLoading

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

  // Back-compat sha for consumers that key off it (ComparePage); undefined when
  // nothing is explicitly selected, matching the prior empty-store behaviour.
  const selectedSha = selVersion?.sha ?? selCommit?.sha

  // When a job transitions to a terminal state, refresh project + versions +
  // documents so every page leaves the "running" / empty state automatically.
  const qc = useQueryClient()
  const jobStatus = job?.status
  useEffect(() => {
    if (!projectId || (jobStatus !== 'complete' && jobStatus !== 'failed')) return
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
    qc.invalidateQueries({ queryKey: projectKeys.versions(projectId) })
    qc.invalidateQueries({ queryKey: projectKeys.commits(projectId) })
    qc.invalidateQueries({ queryKey: ['projects', projectId, 'documents'] })
  }, [jobStatus, projectId, qc])

  return { pageState, isLoading, viewVersion, viewVersionId: viewVersion?.id, selectedCommit: selCommit, selectedSha }
}
