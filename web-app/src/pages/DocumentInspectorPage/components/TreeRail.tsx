import { Icon } from '../../../components/ui'

/* The document list, folded: a thin rail that opens it again. */
export function TreeRail({ onOpen }: { onOpen: () => void }) {
  return (
    <aside className="w-8 flex-shrink-0 bg-surface-container-lowest border-r border-outline-variant flex flex-col items-center pt-2">
      <button
        type="button"
        onClick={onOpen}
        title="Show the document list"
        aria-label="Show the document list"
        className="w-full flex flex-col items-center gap-2 py-1.5 text-on-surface-variant hover:text-secondary hover:bg-surface-container-low"
      >
        <Icon name="left_panel_open" size={18} />
        <span className="[writing-mode:vertical-rl] font-mono text-label font-semibold uppercase tracking-[0.1em]">Documents</span>
      </button>
    </aside>
  )
}
