import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { matchBranches } from '../helpers'

/* Step 1's branch: ONE box to search and pick in (a repository can have hundreds of branches).
   It shows the picked branch; a click, the chevron or ↓ opens every branch; typing replaces the
   text and filters them; ↑/↓ + Enter or a click picks. Esc, Tab or leaving the box keeps the
   branch picked before: text typed and not picked is dropped. */

export function BranchPicker({ branches, value, defaultBranch, invalid, onPick }: {
  branches: string[]
  /** The picked branch. */
  value: string
  /** The repository's default branch: tagged in the list. */
  defaultBranch?: string
  invalid?: boolean
  /** Called with another branch than `value`. */
  onPick: (branch: string) => void
}) {
  const listId = useId()
  const box = useRef<HTMLInputElement>(null)
  const list = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  // What is typed; null while nothing is (the box shows the picked branch).
  const [query, setQuery] = useState<string | null>(null)
  // The row the arrows are on.
  const [active, setActive] = useState(-1)
  // The click that opened the list selected the text (typing replaces it): its mouseup must not
  // put a caret in the selection's place.
  const keepSelection = useRef(false)

  const shown = matchBranches(branches, query ?? '')
  const typed = query?.trim() ?? ''

  // The row under the arrows in view - by scrolling the list alone: scrollIntoView scrolled the
  // page too, which slid another row under a still mouse, and its hover took the arrows' place.
  useEffect(() => {
    const lb = list.current
    const row = open && active >= 0 ? lb?.querySelector<HTMLElement>(`[data-i="${active}"]`) : null
    if (!lb || !row) return
    if (row.offsetTop < lb.scrollTop) lb.scrollTop = row.offsetTop
    else if (row.offsetTop + row.offsetHeight > lb.scrollTop + lb.clientHeight) {
      lb.scrollTop = row.offsetTop + row.offsetHeight - lb.clientHeight
    }
  }, [open, active])

  function openList() {
    if (open || !branches.length) return
    setOpen(true)
    setQuery(null)
    setActive(branches.indexOf(value))
    box.current?.select()
    keepSelection.current = true
  }
  function close() {
    setOpen(false)
    setQuery(null)
    setActive(-1)
  }
  function pick(b: string) {
    close()
    if (b !== value) onPick(b)
  }
  function type(text: string) {
    setQuery(text)
    setOpen(true)
    // While typing, the first match is under the arrows (Enter picks it); cleared, the picked branch.
    setActive(text.trim() ? (matchBranches(branches, text).length ? 0 : -1) : branches.indexOf(value))
  }
  function onKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    keepSelection.current = false
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) { openList(); return }
      if (!shown.length) return
      const step = e.key === 'ArrowDown' ? 1 : -1
      setActive((i) => Math.max(0, Math.min(shown.length - 1, i + step)))
    } else if (e.key === 'Enter') {
      if (!open) return
      e.preventDefault()
      if (shown[active]) pick(shown[active])
    } else if (e.key === 'Escape' && open) {
      e.preventDefault()
      e.stopPropagation()
      close()
    }
  }

  return (
    <div className="relative">
      <Icon name="call_split" size={16} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-outline pointer-events-none" />
      <input
        ref={box}
        className={cn('inp mono with-icon with-chevron', invalid && 'err')}
        type="text"
        autoComplete="off"
        spellCheck={false}
        role="combobox"
        aria-label="Branch"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        placeholder="Search or pick a branch…"
        value={query ?? value}
        onFocus={openList}
        onClick={openList}
        onMouseUp={(e) => { if (keepSelection.current) { e.preventDefault(); keepSelection.current = false } }}
        onChange={(e) => type(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={close}
      />
      {/* The chevron opens and closes the list; focus stays in the box. */}
      <button
        type="button"
        tabIndex={-1}
        aria-label={open ? 'Close the branch list' : 'Open the branch list'}
        onMouseDown={(e) => {
          e.preventDefault()
          if (open) close()
          else if (document.activeElement !== box.current) box.current?.focus()
          else openList()
        }}
        className="absolute right-2 top-1/2 -translate-y-1/2 flex text-outline hover:text-on-surface-variant transition-colors"
      >
        <Icon name="expand_more" size={20} className={cn('transition-transform', open && 'rotate-180')} />
      </button>

      {open && (
        <div
          ref={list}
          id={listId}
          role="listbox"
          aria-label="Branches"
          className="absolute top-[calc(100%+4px)] inset-x-0 z-20 max-h-[248px] overflow-y-auto bg-surface-container-lowest border border-outline-variant rounded-xl shadow-[0_4px_16px_rgba(4,22,39,.12)]"
        >
          {typed && (
            <div className="px-3 py-1.5 border-b border-surface-container-low font-mono text-caption text-outline">
              {shown.length} of {branches.length} branches
            </div>
          )}
          {!shown.length && (
            <div className="px-3 py-2.5 text-xs text-outline">No branch matches “{typed}”</div>
          )}
          {shown.map((b, i) => (
            <div
              key={b}
              id={`${listId}-${i}`}
              data-i={i}
              role="option"
              aria-selected={b === value}
              onMouseDown={(e) => { e.preventDefault(); pick(b) }}
              onMouseMove={() => { if (i !== active) setActive(i) }}
              className={cn(
                'flex items-center gap-2 px-3 py-[7px] cursor-pointer font-mono text-xs',
                i === active && 'bg-surface-container-low',
                b === value ? 'text-secondary font-semibold' : 'text-on-surface',
              )}
            >
              <span className="flex-1 min-w-0 truncate">{b}</span>
              {b === defaultBranch && (
                <span className="px-1.5 rounded-[3px] bg-surface-container text-secondary text-label font-semibold">default</span>
              )}
              {b === value && <Icon name="check" size={16} />}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
