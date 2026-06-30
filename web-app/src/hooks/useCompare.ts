import { useQuery } from '@tanstack/react-query'
import { compareApi } from '../services/api'
import { projectKeys } from './useProjects'

export function useCompareSummary(projectId: string, current?: string, baseline?: string) {
  return useQuery({
    queryKey: [...projectKeys.compare(projectId, current ?? '', baseline ?? ''), 'summary'],
    queryFn: () => compareApi.summary(projectId, current as string, baseline as string),
    enabled: !!projectId && !!current && !!baseline,
  })
}

export function useCompareDocuments(projectId: string, current?: string, baseline?: string) {
  return useQuery({
    queryKey: [...projectKeys.compare(projectId, current ?? '', baseline ?? ''), 'documents'],
    queryFn: () => compareApi.documents(projectId, current as string, baseline as string),
    enabled: !!projectId && !!current && !!baseline,
  })
}

export function useCompareDocumentDetail(
  projectId: string,
  docId?: string,
  current?: string,
  baseline?: string,
) {
  return useQuery({
    queryKey: [...projectKeys.compare(projectId, current ?? '', baseline ?? ''), 'doc', docId ?? ''],
    queryFn: () => compareApi.documentDetail(projectId, docId as string, current as string, baseline as string),
    enabled: !!projectId && !!docId && !!current && !!baseline,
  })
}
