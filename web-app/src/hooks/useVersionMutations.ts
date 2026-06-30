import { useMutation, useQueryClient } from '@tanstack/react-query'
import { versionsApi } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'

function useVersionsInvalidate(projectId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: projectKeys.versions(projectId) })
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
  }
}

export function useCreateVersion(projectId: string) {
  const invalidate = useVersionsInvalidate(projectId)
  return useMutation({
    mutationFn: (body: { tag: string; commit_sha: string; branch?: string; description?: string }) =>
      versionsApi.create(projectId, body),
    onSuccess: (v) => { invalidate(); toast.success('Version tagged', v.tag) },
    onError: (e: Error) => toast.error('Could not tag version', e.message),
  })
}

export function useUpdateVersion(projectId: string) {
  const invalidate = useVersionsInvalidate(projectId)
  return useMutation({
    mutationFn: ({ versionId, ...body }: { versionId: string; status?: string; description?: string }) =>
      versionsApi.update(projectId, versionId, body),
    onSuccess: () => { invalidate(); toast.success('Version updated') },
    onError: (e: Error) => toast.error('Update failed', e.message),
  })
}

export function useDeleteVersion(projectId: string) {
  const invalidate = useVersionsInvalidate(projectId)
  return useMutation({
    mutationFn: (versionId: string) => versionsApi.remove(projectId, versionId),
    onSuccess: () => { invalidate(); toast.success('Version deleted') },
    onError: (e: Error) => toast.error('Delete failed', e.message),
  })
}
