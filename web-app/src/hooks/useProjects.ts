import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  projectsApi, versionsApi, documentsApi, teamApi, commitsApi,
  type CreateProjectInput, type DocumentFilters,
} from '../services/api'
import { useAuthStore } from '../store/auth'
import { toast } from '../components/ui/Toast'

export const projectKeys = {
  all: ['projects'] as const,
  /** Every user's projects list (the prefix of `list`). */
  lists: ['projects', 'list'] as const,
  list: (userEmail?: string) => ['projects', 'list', userEmail ?? 'anon'] as const,
  /** NB: a prefix of every key of the project — invalidate it with `exact: true`. */
  detail: (id: string) => ['projects', id] as const,
  versions: (id: string) => ['projects', id, 'versions'] as const,
  /** A version's components and the state of their documents (staged generation). */
  versionComponents: (id: string, vid: string) => ['projects', id, 'versions', vid, 'components'] as const,
  /** GET /projects/{pid}/runs: runs at work now or cut short, whichever front door started them. */
  runs: (id: string) => ['projects', id, 'runs'] as const,
  /** Every documents read of the project: lists, details, stats, renders, events. */
  documentsAll: (id: string) => ['projects', id, 'documents'] as const,
  documents: (id: string, filters?: DocumentFilters) =>
    ['projects', id, 'documents', filters ?? {}] as const,
  document: (id: string, docId: string) =>
    ['projects', id, 'documents', 'detail', docId] as const,
  documentRender: (id: string, docId: string) =>
    ['projects', id, 'documents', 'render', docId] as const,
  /** Every rendered document of the project: a label save changes SWE.3 and SWE.4 renders. */
  documentRenders: (id: string) => ['projects', id, 'documents', 'render'] as const,
  /** A10: one document's review record. */
  documentEvents: (id: string, docId: string) => ['projects', id, 'documents', 'events', docId] as const,
  /** A11: the project's review record (per version, or all). */
  reviewEvents: (id: string, vid?: string) => ['projects', id, 'review-events', vid ?? 'all'] as const,
  reviewEventsAll: (id: string) => ['projects', id, 'review-events'] as const,
  /** Review & update, per version (its own prefix, so no document or version refetch wipes it). */
  review: (id: string, vid: string) => ['projects', id, 'review', vid] as const,
  exportReadiness: (id: string, vid: string) => ['projects', id, 'review', vid, 'readiness'] as const,
  /** A15: R9 for one document's component and type (under the version's, so both refresh together). */
  documentReadiness: (id: string, vid: string, docId: string) =>
    ['projects', id, 'review', vid, 'readiness', docId] as const,
  overrides: (id: string, vid: string) => ['projects', id, 'review', vid, 'overrides'] as const,
  /** R10: what the next run rewrites (a save refreshes it with the version's review reads). */
  regenerationQueue: (id: string, vid: string) => ['projects', id, 'review', vid, 'queue'] as const,
  slotHistory: (id: string, vid: string, kind: string, key: string) =>
    ['projects', id, 'review', vid, 'history', kind, key] as const,
  flowchartLabels: (id: string, vid: string, flowchartId: string) =>
    ['projects', id, 'review', vid, 'labels', flowchartId] as const,
  docStats: (id: string, versionId?: string) =>
    ['projects', id, 'documents', 'stats', versionId ?? 'all'] as const,
  team: (id: string) => ['projects', id, 'team'] as const,
  pending: (id: string) => ['projects', id, 'team', 'pending'] as const,
  /** GET /users/search: everyone with an account, by name or email (not per project). */
  userSearch: (q: string) => ['users', 'search', q] as const,
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

/** Every document of ONE version that matches `filters` — all pages: the lists, KPIs, approval bar
 *  and bulk approve count them (the API answers at most 100 a page). Nothing is read until
 *  `filters.versionId` is known: the pages pass no filters while the versions load, and the
 *  unscoped read was every version's documents, all pages, thrown away a moment later. A caller
 *  that names `page` or `perPage` gets that one page, version or not. */
export function useDocuments(projectId: string, filters?: DocumentFilters) {
  const onePage = filters?.page !== undefined || filters?.perPage !== undefined
  return useQuery({
    queryKey: projectKeys.documents(projectId, filters),
    queryFn: () => onePage
      ? documentsApi.list(projectId, filters)
      : documentsApi.listAll(projectId, filters),
    enabled: !!projectId && (onePage || !!filters?.versionId),
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

/** Every commit the project has stored, all pages: the Run modal and the Subbar pick from them,
 *  and the first page alone (20) hid the older ones (the API has no commit search). */
export function useCommits(projectId: string) {
  return useQuery({
    queryKey: projectKeys.commits(projectId),
    queryFn: () => commitsApi.listAll(projectId),
    enabled: !!projectId,
    select: (d) => d.commits,
  })
}

/** Sibling of {@link useCommits} — shares the same query, selects the last
 *  repo-sync time (ISO string or null) for the commit picker. */
export function useCommitsLastSync(projectId: string) {
  return useQuery({
    queryKey: projectKeys.commits(projectId),
    queryFn: () => commitsApi.listAll(projectId),
    enabled: !!projectId,
    select: (d) => d.lastSyncedAt,
  })
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
    onSuccess: (p, body) => {
      qc.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
      qc.invalidateQueries({ queryKey: projectKeys.all })
      if (body.name) toast.success('Project renamed', `Documents already made keep their name; a re-export uses "${p.name}".`)
      else toast.success('Project updated')
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

/** Download the project as a config file (never the access token). A plain action, like
 *  useDownloadDoc; a failure is reported here. */
export function useDownloadProjectConfig(projectId: string) {
  return async (projectName: string): Promise<void> => {
    const base = projectName.replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-+|-+$/g, '') || projectId
    try {
      await projectsApi.downloadConfig(projectId, `${base}.config.json`)
    } catch (e) {
      toast.error('Download failed', (e as Error).message)
    }
  }
}
