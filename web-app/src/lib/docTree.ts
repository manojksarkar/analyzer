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

/** The reviewer filter's value for "Needs a reviewer" (the API's `assignee_id=none`). */
export const NEEDS_REVIEWER = 'none'

/** One choice of the reviewer filter: a reviewer's user id, and their name. */
export interface ReviewerOption { value: string; label: string }

/** The distinct reviewers of a doc set, by name (for the reviewer filter). */
export function buildReviewerOptions(docs: Document[]): ReviewerOption[] {
  const byId = new Map<string, string>()
  for (const d of docs) if (d.reviewer) byId.set(d.reviewer.userId, d.reviewer.name)
  return [...byId].map(([value, label]) => ({ value, label })).sort((a, b) => a.label.localeCompare(b.label))
}

/** Whether a document passes the reviewer filter: '' every one, `none` those without a
 *  reviewer, else those the user (by id) reviews. */
export function matchesReviewer(doc: Pick<Document, 'reviewer'>, filter: string): boolean {
  if (!filter) return true
  if (filter === NEEDS_REVIEWER) return !doc.reviewer
  return doc.reviewer?.userId === filter
}

/** Group docs by process in the canonical order, dropping empty processes. */
export function groupDocsByProcess(docs: Document[]): { process: string; docs: Document[] }[] {
  return DOC_PROCESSES
    .map((process) => ({ process, docs: docs.filter((d) => d.process === process) }))
    .filter((g) => g.docs.length > 0)
}
