import { useEffect, useState } from 'react'
import { useQuery, useMutation, useQueryClient, keepPreviousData } from '@tanstack/react-query'
import { teamApi, usersApi } from '../services/api'
import { projectKeys } from './useProjects'
import { toast } from '../components/ui/Toast'
import { ApiError } from '../lib/http'
import type { UserRole } from '../types'

/** People with an account whose name or email contains `q` (empty: the first few by name), for
 *  adding a member. Asks once the typing pauses; the caller is never in the answer. */
export function useUserSearch(q: string, enabled = true) {
  const [term, setTerm] = useState(q.trim())
  useEffect(() => {
    const t = setTimeout(() => setTerm(q.trim()), 250)
    return () => clearTimeout(t)
  }, [q])
  return useQuery({
    queryKey: projectKeys.userSearch(term),
    queryFn: () => usersApi.search(term),
    enabled,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}

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
      toast.success('Added to the project', v.email)
    },
    onError: (e: Error) => toast.error('Could not add them', e.message),
  })
}

/** A refusal (409, e.g. `LAST_ADMIN`: the project's only admin) says the table was out of date:
 *  show the API's message and read the team again. */
function refusedRefetch(invalidate: () => void, e: Error) {
  if (e instanceof ApiError && e.status === 409) invalidate()
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
    onError: (e: Error) => {
      refusedRefetch(invalidate, e)
      toast.error('Could not change role', e.message)
    },
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
    onError: (e: Error) => {
      refusedRefetch(invalidate, e)
      toast.error('Could not remove member', e.message)
    },
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
