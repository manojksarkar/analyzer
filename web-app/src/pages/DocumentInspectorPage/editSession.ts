import { useCallback, useEffect, useRef, useState } from 'react'
import { saveErrorMessage, useSaveSlot, useUndoSlot } from '../../hooks/useReview'
import type { Slot, SlotSaveResult } from '../../types'
import { isCorrected } from './outline'

/* Cancel in edit mode (docs/ui-mockups/documents.html#cancel, compare.html#cancel). A correction
   saves as its box is left, so Cancel cannot just drop what was typed: it puts back each text
   corrected since Edit was pressed, as it was then — the LLM's text with R4, an earlier correction
   saved again. Flowchart labels are saved in their own dialog, with its own Cancel, and stay. */

/** What a text was before its first change since Edit. */
export type Before = { llm: true } | { llm: false; text: string }

interface Change {
  /** The slot as the last save or undo answered: what a put-back sends (kind, key, ids). */
  now: Slot
  before: Before
}

/** What a text was before the save or undo that answered `r`: the LLM's text when no correction
 *  was in force (`firstEdit`) or the one in force was an undo (its words are the LLM's); else the
 *  correction it replaced. */
export function beforeOf(r: SlotSaveResult): Before {
  if (r.firstEdit || r.previousText === null || r.previousText === r.llmText) return { llm: true }
  return { llm: false, text: r.previousText }
}

/** The text is not as it was before Edit: a save or undo since moved it, and nothing moved it back. */
function changed(c: Change): boolean {
  return c.before.llm ? isCorrected(c.now) : c.now.text !== c.before.text
}

const idOf = (s: Slot) => `${s.kind}\u0000${s.key}`

export interface DiscardResult {
  /** Texts put back. */
  done: number
  /** Why each text that could not be put back could not. */
  failed: string[]
}

/** Save and undo for edit mode, remembering what each text was before Edit; `discard` puts them back. */
export function useEditSession(projectId: string, versionId: string) {
  const { mutateAsync: saveText } = useSaveSlot(projectId, versionId)
  const { mutateAsync: undoText } = useUndoSlot(projectId, versionId)
  // Putting back: one toast for all of them, said by the caller.
  const { mutateAsync: saveBack } = useSaveSlot(projectId, versionId, { quiet: true })
  const { mutateAsync: undoBack } = useUndoSlot(projectId, versionId, { quiet: true })
  const changes = useRef(new Map<string, Change>())
  const inFlight = useRef(new Set<Promise<unknown>>())
  const [discarding, setDiscarding] = useState(false)

  // A session is one version's: the saves of another cannot be put back through this one.
  useEffect(() => { changes.current = new Map() }, [versionId])

  const note = useCallback((r: SlotSaveResult) => {
    const id = idOf(r)
    const had = changes.current.get(id)
    changes.current.set(id, { now: r, before: had ? had.before : beforeOf(r) })
  }, [])
  const track = useCallback(<T>(p: Promise<T>): Promise<T> => {
    inFlight.current.add(p)
    p.finally(() => inFlight.current.delete(p)).catch(() => {})
    return p
  }, [])

  /** R3 / R6; rejects when the save failed (the box says why). */
  const save = useCallback((slot: Slot, text: string) =>
    track(saveText({ slot, text }).then((r) => { note(r); return r })), [saveText, note, track])
  /** R4; a failure is said by the hook's toast. */
  const undo = useCallback((slot: Slot) => {
    track(undoText(slot).then(note)).catch(() => {})
  }, [undoText, note, track])
  /** Edit pressed: nothing to put back yet. */
  const start = useCallback(() => { changes.current = new Map() }, [])
  /** How many texts Cancel would put back — once the saves under way have answered (leaving a box
   *  for the Cancel button saves it). */
  const pending = useCallback(async () => {
    await Promise.allSettled([...inFlight.current])
    return [...changes.current.values()].filter(changed).length
  }, [])
  /** Put every changed text back, one at a time; the session ends either way. */
  const discard = useCallback(async (): Promise<DiscardResult> => {
    setDiscarding(true)
    const result: DiscardResult = { done: 0, failed: [] }
    try {
      for (const c of [...changes.current.values()].filter(changed)) {
        try {
          if (c.before.llm) await undoBack(c.now)
          else await saveBack({ slot: c.now, text: c.before.text })
          result.done++
        } catch (e) {
          result.failed.push(e instanceof Error ? saveErrorMessage(e) : String(e))
        }
      }
    } finally {
      changes.current = new Map()
      setDiscarding(false)
    }
    return result
  }, [undoBack, saveBack])

  return { save, undo, start, pending, discard, discarding }
}

export type EditSession = ReturnType<typeof useEditSession>
