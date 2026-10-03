import { useEffect, useRef } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { versionComponentsApi } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'
import type { VersionComponents } from '../types'

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

export function useGenerateComponents(projectId: string, versionId?: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (components: string[]) =>
      versionComponentsApi.generate(projectId, versionId as string, components),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: projectKeys.versionComponents(projectId, versionId ?? '') })
      qc.invalidateQueries({ queryKey: projectKeys.job(projectId) })
      const n = r.components.length
      toast.success(`Generating ${n} component${n === 1 ? '' : 's'}`,
        r.skipped.length ? `${r.skipped.length} already had documents and were left alone.` : 'Their documents appear here as each is made.')
    },
    onError: (e: Error) => toast.error('Could not start', e.message),
  })
}
