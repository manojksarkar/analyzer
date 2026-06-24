import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  projectsApi, versionsApi, documentsApi, teamApi, commitsApi,
  type CreateProjectInput, type DocumentFilters,
} from '../services/api'
import { useAuthStore } from '../store/auth'
import { toast } from '../components/ui/Toast'

export const projectKeys = {
  all: ['projects'] as const,
  list: (userEmail?: string) => ['projects', 'list', userEmail ?? 'anon'] as const,
  detail: (id: string) => ['projects', id] as const,
  versions: (id: string) => ['projects', id, 'versions'] as const,
  documents: (id: string, filters?: DocumentFilters) =>
    ['projects', id, 'documents', filters ?? {}] as const,
  document: (id: string, docId: string) =>
    ['projects', id, 'documents', 'detail', docId] as const,
  documentRender: (id: string, docId: string) =>
    ['projects', id, 'documents', 'render', docId] as const,
  docStats: (id: string, versionId?: string) =>
    ['projects', id, 'documents', 'stats', versionId ?? 'all'] as const,
  team: (id: string) => ['projects', id, 'team'] as const,
  pending: (id: string) => ['projects', id, 'team', 'pending'] as const,
  commits: (id: string) => ['projects', id, 'commits'] as const,
  job: (id: string) => ['projects', id, 'job'] as const,
  jobFunctions: (id: string, jobId: string) => ['projects', id, 'job', jobId, 'functions'] as const,
  compare: (id: string, current: string, baseline: string) =>
    ['projects', id, 'compare', current, baseline] as const,
}

/* ── Reads ─────────────────────────────────────────────────────────────── */

export function useProjects() {
  // Server scopes the list to the bearer token; we key the cache by user so a
  // re-sign-in as a different account doesn't show stale projects.
  const userEmail = useAuthStore((s) => s.user?.email)
  return useQuery({
    queryKey: projectKeys.list(userEmail),
    queryFn: () => projectsApi.list(),
  })
}

export function useProject(id: string) {
  return useQuery({ queryKey: projectKeys.detail(id), queryFn: () => projectsApi.get(id), enabled: !!id })
}

export function useVersions(projectId: string) {
  return useQuery({ queryKey: projectKeys.versions(projectId), queryFn: () => versionsApi.list(projectId), enabled: !!projectId })
}

export function useDocuments(projectId: string, filters?: DocumentFilters) {
  return useQuery({
    queryKey: projectKeys.documents(projectId, filters),
    queryFn: () => documentsApi.list(projectId, filters),
    enabled: !!projectId,
  })
}

export function useDocument(projectId: string, docId: string) {
  return useQuery({
    queryKey: projectKeys.document(projectId, docId),
    queryFn: () => documentsApi.get(projectId, docId),
    enabled: !!projectId && !!docId,
  })
}

export function useDocumentRender(projectId: string, docId: string) {
  return useQuery({
    queryKey: projectKeys.documentRender(projectId, docId),
    queryFn: () => documentsApi.render(projectId, docId),
    enabled: !!projectId && !!docId,
  })
}

export function useDocStats(projectId: string, versionId?: string) {
  return useQuery({
    queryKey: projectKeys.docStats(projectId, versionId),
    queryFn: () => documentsApi.stats(projectId, versionId),
    enabled: !!projectId,
  })
}

export function useTeam(projectId: string) {
  return useQuery({ queryKey: projectKeys.team(projectId), queryFn: () => teamApi.list(projectId), enabled: !!projectId })
}

export function useCommits(projectId: string) {
  return useQuery({ queryKey: projectKeys.commits(projectId), queryFn: () => commitsApi.list(projectId), enabled: !!projectId })
}

/* ── Project mutations ─────────────────────────────────────────────────── */

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateProjectInput) => projectsApi.create(body),
    onSuccess: (p) => {
      qc.invalidateQueries({ queryKey: projectKeys.all })
      toast.success('Project created', p.name)
    },
    onError: (e: Error) => toast.error('Could not create project', e.message),
  })
}

export function useUpdateProject(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name?: string; client?: string; status?: string }) =>
      projectsApi.update(projectId, body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      qc.invalidateQueries({ queryKey: projectKeys.all })
      toast.success('Project updated')
    },
    onError: (e: Error) => toast.error('Update failed', e.message),
  })
}

export function useDeleteProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (projectId: string) => projectsApi.remove(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.all })
      toast.success('Project deleted')
    },
    onError: (e: Error) => toast.error('Delete failed', e.message),
  })
}

export function useRequestAccess() {
  return useMutation({
    mutationFn: (projectId: string) => projectsApi.requestAccess(projectId),
    onSuccess: () => toast.success('Access requested', 'An admin will review your request.'),
    onError: (e: Error) => toast.error('Request failed', e.message),
  })
}
