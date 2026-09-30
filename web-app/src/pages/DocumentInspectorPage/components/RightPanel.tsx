import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'

export interface PanelTab {
  id: string
  label: string
  count?: number
}

/* The reader's right panel: tabs (Outline · Review · Corrections), collapsible to a thin rail. */
export function RightPanel({
  tabs, active, onTab, collapsed, onToggle, children,
}: {
  tabs: PanelTab[]
  active: string
  onTab: (id: string) => void
  collapsed: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  if (collapsed) {
    return (
      <aside className="w-9 flex-shrink-0 bg-white border-l border-outline-variant flex flex-col items-center py-3">
        <button
          onClick={onToggle}
          title="Show the panel"
          aria-label="Show the panel"
          className="p-1.5 rounded-lg hover:bg-surface-container-low transition-colors text-on-surface-variant"
        >
          <Icon name="chevron_left" size={16} />
        </button>
        <Icon name="toc" size={16} className="text-outline mt-2" />
      </aside>
    )
  }
  return (
    <aside className="w-64 flex-shrink-0 bg-white border-l border-outline-variant flex flex-col overflow-hidden">
      <div className="flex items-center border-b border-outline-variant flex-shrink-0 pl-1 pr-0.5">
        <div role="tablist" className="flex flex-1 min-w-0">
          {tabs.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={active === t.id}
              onClick={() => onTab(t.id)}
              className={cn(
                'flex items-center gap-1 px-1.5 pt-3 pb-2.5 -mb-px border-b-2 font-mono text-caption font-semibold whitespace-nowrap transition-colors',
                active === t.id ? 'border-secondary text-secondary' : 'border-transparent text-outline hover:text-on-surface',
              )}
            >
              {t.label}
              {t.count !== undefined && (
                <span className="px-1.5 rounded-full bg-surface-container text-secondary text-label">{t.count}</span>
              )}
            </button>
          ))}
        </div>
        <button
          onClick={onToggle}
          title="Collapse the panel"
          aria-label="Collapse the panel"
          className="p-1 rounded-lg hover:bg-surface-container-low transition-colors text-on-surface-variant flex-shrink-0"
        >
          <Icon name="chevron_right" size={15} />
        </button>
      </div>
      {children}
    </aside>
  )
}
