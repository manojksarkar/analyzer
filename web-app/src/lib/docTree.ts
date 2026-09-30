import type { Document } from '../types'

/** Process column order shared by the documents list + the tree rail. */
export const DOC_PROCESSES = ['SYS.1', 'SYS.2', 'SWE.1', 'SWE.2', 'SWE.3', 'SWE.4'] as const

/** Each process's document, as the tree names it (docs/ui-mockups/documents.html). */
export const PROCESS_TITLES: Record<string, string> = {
  'SYS.1': 'System Requirements Spec',
  'SYS.2': 'System Test Spec',
  'SWE.1': 'SW Requirements Spec',
  'SWE.2': 'Software Architecture Spec',
  'SWE.3': 'Detailed Design',
  'SWE.4': 'Unit Test Specification',
}

/* The DOCX a process's exporter writes for a component (engine group_planner). */
const DOCX_PREFIX: Record<string, string> = {
  'SWE.3': 'software_detailed_design',
  'SWE.4': 'software_unit_test_specification',
}

/** The name a document downloads under (no extension) — the engine's own file name, so a
 *  component's SWE.3 and SWE.4 never land on one file. */
export function docxFileName(doc: Pick<Document, 'process' | 'group' | 'name'>): string {
  const prefix = DOCX_PREFIX[doc.process]
  return prefix ? `${prefix}_${doc.group ?? doc.name}` : `${doc.process}_${doc.name}`
}

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
