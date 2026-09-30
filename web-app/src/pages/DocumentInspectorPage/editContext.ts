import { createContext, useContext } from 'react'
import type { FlowchartEntry, Slot } from '../../types'

/** What a correctable text needs from the page in edit mode (review & update). */
export interface EditApi {
  /** Edit mode is on: correctable texts become boxes. */
  editing: boolean
  /** A run or a re-export is going: the boxes are read-only until it ends. */
  locked: boolean
  projectId: string
  versionId: string
  /** Save one text (R3, or R6 for bullets). Rejects when the save failed. */
  save: (slot: Slot, text: string) => Promise<unknown>
  /** Back to the LLM's wording (R4). */
  undo: (slot: Slot) => void
  /** Open the label editor of one flowchart. */
  openFlowchart: (chart: FlowchartEntry) => void
  /** A user id (`updatedBy`) as a name. */
  userName: (userId: string | null) => string
}

export const EditContext = createContext<EditApi | null>(null)

export function useEdit(): EditApi | null {
  return useContext(EditContext)
}

/** The longest text a save sends (the API sets no limit yet — BACKLOG RF-10). */
export const MAX_TEXT = 2000
