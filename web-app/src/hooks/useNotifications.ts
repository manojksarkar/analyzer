import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { notificationsApi } from '../services/api'
import { useAuthStore } from '../store/auth'

const notifKeys = {
  list: (userId?: string) => ['notifications', userId ?? 'anon'] as const,
}

export function useNotifications() {
  const userId = useAuthStore((s) => s.user?.id)
  const isAuthed = useAuthStore((s) => s.isAuthenticated)
  return useQuery({
    queryKey: notifKeys.list(userId),
    queryFn: () => notificationsApi.list(),
    enabled: isAuthed,
    refetchInterval: 60000,
  })
}

export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
}

export function useMarkAllNotificationsRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
}
