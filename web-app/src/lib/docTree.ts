import type { Document } from '../types'

/** Process column order shared by the documents list + the tree rail. */
export const DOC_PROCESSES = ['SYS.1', 'SYS.2', 'SWE.1', 'SWE.3'] as const

/** Distinct, sorted assignee names from a doc set (for the rail dropdown). */
export function buildAssigneeOptions(docs: Document[]): string[] {
  return [...new Set(docs.map((d) => d.assignee).filter((a): a is string => !!a))].sort()
}

/** Group docs by process in the canonical order, dropping empty processes. */
export function groupDocsByProcess(docs: Document[]): { process: string; docs: Document[] }[] {
  return DOC_PROCESSES
    .map((process) => ({ process, docs: docs.filter((d) => d.process === process) }))
    .filter((g) => g.docs.length > 0)
}
