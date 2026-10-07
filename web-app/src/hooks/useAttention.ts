import { useCurrentJob } from './useJobs'
import { useProjectViewState } from './useProjectViewState'
import { useProjectRuns, useVersionComponents } from './useVersionComponents'
import { failureSuperseded, generationItem, type AttentionItem } from '../lib/attention'

/** What needs attention in the project (lib/attention.ts): read from what the Overview read for its
 *  banners -- the current job, the version on screen and its components, the project's runs.
 *  `exceptVersionIds`: the versions whose run another item says already. */
export function useAttention(projectId: string): { items: AttentionItem[]; exceptVersionIds: (string | null | undefined)[] } {
  const { data: job } = useCurrentJob(projectId)
  const { pageState, viewVersion } = useProjectViewState(projectId)
  // A first run at work has the Overview's running card: nothing else to say about it here.
  const running = pageState === 'running'
  const failedJob = job?.status === 'failed' && !running ? job : undefined
  const { data: failedComps } = useVersionComponents(projectId, failedJob?.versionId ?? undefined)
  const { data: viewComps } = useVersionComponents(projectId, running ? undefined : viewVersion?.id)
  const { data: runs } = useProjectRuns(projectId)

  const items: AttentionItem[] = []
  if (failedJob && !failureSuperseded(failedJob, failedComps)) items.push({ kind: 'failed', job: failedJob })
  const gen = running ? null : generationItem(viewVersion, viewComps)
  if (gen) items.push(gen)
  const exceptVersionIds = [running ? job?.versionId : null, viewVersion?.id]
  const others = (runs ?? []).filter((r) => !exceptVersionIds.includes(r.versionId))
  if (others.length) items.push({ kind: 'runs', runs: others })
  if (viewVersion && viewVersion.warnings.length > 0 && !running) items.push({ kind: 'warnings', version: viewVersion })
  return { items, exceptVersionIds }
}
