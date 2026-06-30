import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { teamApi } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'
import type { UserRole } from '../types'

export function usePendingMembers(projectId: string, enabled = true) {
  return useQuery({
    queryKey: projectKeys.pending(projectId),
    queryFn: () => teamApi.listPending(projectId),
    enabled: !!projectId && enabled,
  })
}

function useTeamInvalidate(projectId: string) {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: projectKeys.team(projectId) })
    qc.invalidateQueries({ queryKey: projectKeys.pending(projectId) })
    qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
  }
}

export function useInviteMember(projectId: string) {
  const invalidate = useTeamInvalidate(projectId)
  return useMutation({
    mutationFn: ({ email, role }: { email: string; role: UserRole }) =>
      teamApi.invite(projectId, email, role),
    onSuccess: (_d, v) => {
      invalidate()
      toast.success('Invite sent', v.email)
    },
    onError: (e: Error) => toast.error('Invite failed', e.message),
  })
}

export function useUpdateMemberRole(projectId: string) {
  const invalidate = useTeamInvalidate(projectId)
  return useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: UserRole }) =>
      teamApi.updateRole(projectId, userId, role),
    onSuccess: () => {
      invalidate()
      toast.success('Role updated')
    },
    onError: (e: Error) => toast.error('Could not change role', e.message),
  })
}

export function useRemoveMember(projectId: string) {
  const invalidate = useTeamInvalidate(projectId)
  return useMutation({
    mutationFn: (userId: string) => teamApi.remove(projectId, userId),
    onSuccess: () => {
      invalidate()
      toast.success('Member removed')
    },
    onError: (e: Error) => toast.error('Could not remove member', e.message),
  })
}

export function useCancelInvite(projectId: string) {
  const invalidate = useTeamInvalidate(projectId)
  return useMutation({
    mutationFn: (inviteId: string) => teamApi.cancelInvite(projectId, inviteId),
    onSuccess: () => {
      invalidate()
      toast.success('Invite cancelled')
    },
    onError: (e: Error) => toast.error('Could not cancel invite', e.message),
  })
}
