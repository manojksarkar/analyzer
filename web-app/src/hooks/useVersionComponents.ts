import { useEffect, useRef } from 'react'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import { versionComponentsApi } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'
import type { ProjectRun, VersionComponents } from '../types'

/* Staged generation: a version's components, the state of their documents, its latest run — and
   making the documents of the ones not generated yet. */

/** While anything is being made (a live run, or components waiting / being made), read again
 *  every 10 s; otherwise once. */
export function componentsBusy(data?: VersionComponents): boolean {
  if (!data) return false
  if (data.run?.alive || data.job) return true
  return data.components.some((c) => c.state === 'generating' || (c.state === 'waiting' && data.run?.alive !== false))
}

/** `pollUntil` (ms since epoch): read again every 10 s until then too. Right after Generate the
 *  export has not taken the version or marked anything yet, so the data alone says "idle". */
export function useVersionComponents(projectId: string, versionId?: string, pollUntil = 0) {
  const query = useQuery({
    queryKey: projectKeys.versionComponents(projectId, versionId ?? ''),
    queryFn: () => versionComponentsApi.list(projectId, versionId as string),
    enabled: !!projectId && !!versionId,
    refetchInterval: (q) => (componentsBusy(q.state.data) || Date.now() < pollUntil ? 10_000 : false),
  })
  // A component that finishes has new documents: read the list again when the count moves.
  const qc = useQueryClient()
  const generated = query.data?.counts.generated ?? 0
  const seen = useRef<number | null>(null)
  useEffect(() => {
    if (seen.current !== null && generated !== seen.current) {
      qc.invalidateQueries({ queryKey: projectKeys.documentsAll(projectId) })
    }
    seen.current = generated
  }, [generated, projectId, qc])
  return query
}

/** How often the runs are read again: every 15 s while one is alive, else every minute — a run
 *  started from the command line (`--detach`) after the page loaded must show up, and a
 *  "Stopped" card go once it is resumed or discarded. (Reading only while one was alive, an
 *  Overview that loaded without a live run never saw one.) */
export function runsPollMs(runs: ProjectRun[] | undefined): number {
  return runs?.some((r) => r.alive) ? 15_000 : 60_000
}

/** The project's runs at work now or cut short (a web job, or `analyzer.py` on the server, which
 *  the Overview could not see). A run started or ended here reads them again at once. */
export function useProjectRuns(projectId: string) {
  return useQuery({
    queryKey: projectKeys.runs(projectId),
    queryFn: () => versionComponentsApi.runs(projectId),
    enabled: !!projectId,
    refetchInterval: (q) => runsPollMs(q.state.data),
  })
}

/** The runs of many projects at once (Live logs: every project a superuser sees), each read on
 *  the same key and schedule as `useProjectRuns`. Newest progress first. */
export function useAllProjectRuns(projectIds: string[]) {
  return useQueries({
    queries: projectIds.map((id) => ({
      queryKey: projectKeys.runs(id),
      queryFn: () => versionComponentsApi.runs(id),
      refetchInterval: (q: { state: { data?: ProjectRun[] } }) => runsPollMs(q.state.data),
    })),
    combine: (results) => ({
      runs: results.flatMap((r, i) => (r.data ?? []).map((run) => ({ projectId: projectIds[i], run }))),
      // Still reading some project's runs: "no run" would be a guess.
      pending: results.some((r) => r.isPending),
    }),
  })
}

/** What the version's run has found so far, read again every 10 s while it runs. */
export function useRunFacts(projectId: string, versionId: string | null | undefined, live: boolean) {
  return useQuery({
    queryKey: projectKeys.runFacts(projectId, versionId ?? ''),
    queryFn: () => versionComponentsApi.runFacts(projectId, versionId as string),
    enabled: !!projectId && !!versionId,
    refetchInterval: live ? 10_000 : false,
  })
}

/** Resume a version whose run stopped before it finished: the job takes the banner's running row. */
export function useResumeVersion(projectId: string, versionId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => versionComponentsApi.resume(projectId, versionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.versionComponents(projectId, versionId) })
      qc.invalidateQueries({ queryKey: projectKeys.job(projectId) })
      qc.invalidateQueries({ queryKey: projectKeys.runs(projectId) })
      toast.success('Resuming', 'The run carries on from where it stopped.')
    },
    onError: (e: Error) => toast.error('Could not resume', e.message),
  })
}

export function useGenerateComponents(projectId: string, versionId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (components: string[]) =>
      versionComponentsApi.generate(projectId, versionId as string, components),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: projectKeys.versionComponents(projectId, versionId ?? '') })
      qc.invalidateQueries({ queryKey: projectKeys.job(projectId) })
      qc.invalidateQueries({ queryKey: projectKeys.runs(projectId) })
      const n = r.components.length
      const detail = r.addedLayers.length
        ? `${r.addedLayers.join(', ')} is added to this version first (parse + descriptions); then the documents.`
        : r.skipped.length ? `${r.skipped.length} already had documents and were left alone.` : 'Their documents appear here as each is made.'
      toast.success(`Generating ${n} component${n === 1 ? '' : 's'}`, detail)
    },
    onError: (e: Error) => toast.error('Could not start', e.message),
  })
}
