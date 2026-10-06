/** A run's lines in Live logs (superusers): the page filtered to its job when there is one (a web
 *  run), else to its version (a command-line run has no job). The version picks it in Runs. */
export function liveLogsHref(projectId: string, versionId?: string | null, jobId?: string | null): string {
  const q = new URLSearchParams({ project: projectId })
  if (versionId) q.set('version', versionId)
  if (jobId) q.set('job', jobId)
  return `/admin/logs?${q.toString()}`
}
