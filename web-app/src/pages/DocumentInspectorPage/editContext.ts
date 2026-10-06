import { createContext, useContext } from 'react'
import type { FlowchartEntry, Slot } from '../../types'

/** What a correctable text needs from the page in edit mode (review & update). */
export interface EditApi {
  /** Edit mode is on: correctable texts become boxes. */
  editing: boolean
  /** A run rebuilds the version, or an update writes this document's Word file: the boxes are
   *  read-only until it ends. */
  locked: boolean
  projectId: string
  versionId: string
  /** Save one text (R3, or R6 for bullets). Rejects when the save failed. */
  save: (slot: Slot, text: string) => Promise<unknown>
  /** Back to the LLM's wording (R4). */
  undo: (slot: Slot) => void
  /** Open the label editor of one flowchart. */
  openFlowchart: (chart: FlowchartEntry) => void
  /** Why the flowchart labels cannot be corrected (the component's SWE.4 is approved: its test
   *  steps are built from them), or null. */
  labelsLocked: string | null
  /** A user id (`updatedBy`) as a name. */
  userName: (userId: string | null) => string
}

export const EditContext = createContext<EditApi | null>(null)

export function useEdit(): EditApi | null {
  return useContext(EditContext)
}

/** The longest text a save sends. The API refuses more than 10,000 characters (422) — one text,
 *  one label, or a behaviour row's bullets together with their line breaks (RF-10); the page
 *  keeps a correction well under that. */
export const MAX_TEXT = 2000

/** U+0000: the API refuses it in any save (422 — PostgreSQL cannot store it), so the page stops
 *  it before sending. A paste from a binary or a mangled file can carry one. */
export function hasNul(text: string): boolean {
  return text.includes('\u0000')
}

export const NUL_MESSAGE = 'The text contains a NUL character (U+0000), which cannot be saved — remove it. Nothing was saved.'
