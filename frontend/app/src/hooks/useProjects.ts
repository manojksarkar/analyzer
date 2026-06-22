import { useQuery } from '@tanstack/react-query'
import { projectsApi, versionsApi, documentsApi, teamApi, commitsApi } from '../services/api'

export const projectKeys = {
  all: ['projects'] as const,
  detail: (id: string) => ['projects', id] as const,
  versions: (id: string) => ['projects', id, 'versions'] as const,
  documents: (id: string) => ['projects', id, 'documents'] as const,
  team: (id: string) => ['projects', id, 'team'] as const,
  commits: (id: string) => ['projects', id, 'commits'] as const,
}

export function useProjects() {
  return useQuery({ queryKey: projectKeys.all, queryFn: projectsApi.list })
}

export function useProject(id: string) {
  return useQuery({ queryKey: projectKeys.detail(id), queryFn: () => projectsApi.get(id), enabled: !!id })
}

export function useVersions(projectId: string) {
  return useQuery({ queryKey: projectKeys.versions(projectId), queryFn: () => versionsApi.list(projectId), enabled: !!projectId })
}

export function useDocuments(projectId: string) {
  return useQuery({ queryKey: projectKeys.documents(projectId), queryFn: () => documentsApi.list(projectId), enabled: !!projectId })
}

export function useTeam(projectId: string) {
  return useQuery({ queryKey: projectKeys.team(projectId), queryFn: () => teamApi.list(projectId), enabled: !!projectId })
}

export function useCommits(projectId: string) {
  return useQuery({ queryKey: projectKeys.commits(projectId), queryFn: () => commitsApi.list(projectId), enabled: !!projectId })
}
