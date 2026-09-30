import { useLayoutEffect, useRef, useState } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { formatShortDate } from '../../../lib/format'
import { useSlotHistory } from '../../../hooks/useReview'
import type { Slot } from '../../../types'
import { MAX_TEXT, useEdit, type EditApi } from '../editContext'

/* A text of the document that a reviewer can correct (review & update). Read mode prints it as
   the document does, with a small mark when a correction is in force. Edit mode turns it into a
   box that saves on its own when you leave it (Enter too; Esc cancels) — one text per save,
   as the API takes them. */

interface Props {
  slot: Slot | null | undefined
  /** What the page prints: the slot's text, or the document's stand-in when it has none. */
  display: string
  /** A behaviour row: one bullet per line. */
  bullets?: string[]
  className?: string
}

export function SlotText({ slot, display, bullets, className }: Props) {
  const edit = useEdit()
  if (!slot || !edit?.editing) {
    return (
      <div data-slot-key={slot?.key} className={cn('whitespace-pre-line', className)}>
        {bullets ? (
          <BulletList items={bullets} mark={slot?.isOverridden ? <CorrectedMark slot={slot} edit={edit} /> : null} />
        ) : (
          <>
            {slot?.isOverridden && <CorrectedMark slot={slot} edit={edit} />}
            {display}
          </>
        )}
      </div>
    )
  }
  // Remounts when a save (or another reviewer's) changes the slot, so the box holds the new text.
  return (
    <SlotEditor
      key={`${slot.key}|${slot.updatedAt ?? ''}|${slot.text}`}
      slot={slot}
      display={display}
      list={!!bullets}
      edit={edit}
      className={className}
    />
  )
}

/** A behaviour row's bullets; the corrected mark, when there is one, leads the first line. */
function BulletList({ items, mark }: { items: string[]; mark: React.ReactNode }) {
  if (!items.length) return <span className="text-on-surface-variant">{mark}-</span>
  return <>{items.map((b, i) => <p key={i}>{i === 0 && mark}• {b}</p>)}</>
}

function CorrectedMark({ slot, edit }: { slot: Slot; edit: EditApi | null }) {
  const who = edit?.userName(slot.updatedBy) ?? ''
  const title = `Corrected${who ? ` by ${who}` : ''}${slot.updatedAt ? `, ${formatShortDate(slot.updatedAt)}` : ''}.`
    + (slot.llmText ? ` The LLM wrote: “${slot.llmText}”` : '')
  return (
    <span
      title={title}
      aria-label="Corrected by a reviewer"
      className="inline-block w-1.5 h-1.5 rounded-full bg-secondary mr-1.5 align-middle"
    />
  )
}

function normalise(text: string, list: boolean): string {
  if (list) return text.split('\n').map((l) => l.replace(/^\s*[•-]\s*/, '').trim()).filter(Boolean).join('\n')
  return text.trim()
}

function SlotEditor({ slot, display, list, edit, className }: {
  slot: Slot; display: string; list: boolean; edit: EditApi; className?: string
}) {
  const initial = list ? (slot.bullets ?? []).join('\n') : slot.text
  const [draft, setDraft] = useState(initial)
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle')
  const [message, setMessage] = useState<string | null>(null)
  const [showHistory, setShowHistory] = useState(false)
  const ref = useRef<HTMLTextAreaElement>(null)
  const cancelled = useRef(false)

  useLayoutEffect(() => { grow(ref.current) }, [draft])

  async function commit() {
    if (cancelled.current) {
      cancelled.current = false
      setDraft(initial)
      return
    }
    const text = normalise(draft, list)
    if (text === normalise(initial, list)) return
    if (!text) {
      setMessage(list ? 'Keep at least one bullet. Nothing was saved.' : 'A text can’t be empty. Nothing was saved.')
      setDraft(initial)
      return
    }
    if (text.length > MAX_TEXT) {
      setMessage(`Keep it under ${MAX_TEXT.toLocaleString()} characters. Nothing was saved.`)
      return
    }
    setMessage(null)
    setState('saving')
    try {
      await edit.save(slot, text)
      setState('idle')
    } catch {
      setState('error')
      setMessage('Not saved — your text is still here. Leave the box again to retry.')
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Escape') {
      cancelled.current = true
      e.currentTarget.blur()
    } else if (e.key === 'Enter' && (list ? (e.ctrlKey || e.metaKey) : !e.shiftKey)) {
      e.preventDefault()
      e.currentTarget.blur()
    }
  }

  const who = edit.userName(slot.updatedBy)
  return (
    <div data-slot-key={slot.key} className={className}>
      <textarea
        ref={ref}
        value={draft}
        rows={1}
        readOnly={edit.locked}
        placeholder={slot.text ? undefined : display}
        aria-label="Correct this text"
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => { void commit() }}
        onKeyDown={onKeyDown}
        className={cn(
          'block w-full resize-none overflow-hidden rounded-[3px] px-1.5 py-0.5 -mx-1.5',
          'bg-[#fbfcff] outline-dashed outline-1 outline-[#8aa4d6] outline-offset-0',
          'hover:outline-solid hover:outline-secondary hover:bg-surface-container-low',
          'focus:outline-2 focus:outline-solid focus:outline-secondary focus:bg-white',
          'placeholder:text-outline placeholder:italic',
          edit.locked && 'outline-outline-variant cursor-not-allowed bg-transparent',
        )}
      />
      <div className="mt-1 font-mono text-label text-outline flex flex-wrap items-center gap-x-1.5">
        {state === 'saving' && <span>Saving…</span>}
        {message && <span className={state === 'error' ? 'text-error font-semibold' : 'text-error'}>{message}</span>}
        {state !== 'saving' && !message && slot.isOverridden && (
          <>
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-secondary" aria-hidden />
            <span>Corrected{who ? ` by ${who}` : ''}{slot.updatedAt ? ` · ${formatShortDate(slot.updatedAt)}` : ''}</span>
            {slot.canUndo && !edit.locked && (
              <>· <button type="button" onClick={() => edit.undo(slot)} className="text-secondary hover:underline">Undo</button></>
            )}
          </>
        )}
        {state !== 'saving' && !message && !slot.isOverridden && !slot.text && (
          <span>No text of its own yet — the page shows a stand-in</span>
        )}
        {state !== 'saving' && (slot.isOverridden || slot.isOrphaned) && (
          <>
            {(slot.isOverridden || message) && <span>·</span>}
            <button type="button" onClick={() => setShowHistory((v) => !v)} className="text-secondary hover:underline">
              {showHistory ? 'Hide history' : 'History'}
            </button>
          </>
        )}
      </div>
      {showHistory && <SlotHistory slot={slot} edit={edit} />}
    </div>
  )
}

function grow(el: HTMLTextAreaElement | null) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight}px`
}

function SlotHistory({ slot, edit }: { slot: Slot; edit: EditApi }) {
  const { data, isLoading, isError } = useSlotHistory(edit.projectId, edit.versionId, slot, true)
  return (
    <div className="mt-1.5 border border-outline-variant rounded-lg bg-surface px-2.5 py-2 text-caption">
      <p className="font-mono text-label font-semibold uppercase tracking-[0.06em] text-on-surface-variant mb-1">History, oldest first</p>
      {slot.llmText && (
        <HistoryRow who="LLM" text={slot.llmText} />
      )}
      {isLoading && <p className="text-outline">Loading…</p>}
      {isError && (
        <p className="flex items-center gap-1 text-error"><Icon name="error" size={12} />Could not read the history.</p>
      )}
      {data?.map((e) => (
        <HistoryRow
          key={e.seq}
          who={`${edit.userName(e.updatedBy) || 'Someone'}${e.updatedAt ? ` · ${formatShortDate(e.updatedAt)}` : ''}`}
          text={e.humanText}
        />
      ))}
    </div>
  )
}

function HistoryRow({ who, text }: { who: string; text: string }) {
  return (
    <div className="py-1 border-t border-surface-container first:border-t-0">
      <p className="font-mono text-label text-outline">{who}</p>
      <p className="text-on-surface whitespace-pre-line">{text}</p>
    </div>
  )
}
