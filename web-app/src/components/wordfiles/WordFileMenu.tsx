import type { ReactNode } from 'react'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { Icon } from '../ui'
import { cn } from '../../lib/cn'

/* A small menu whose items carry a line under them (documents.html .wf-menu): a download's
   *Corrected file* ("Updated first") / *Current file* (why it is out of date), an admin's
   *Rebuild all Word files…*. An item that cannot run now is off, its line saying why. */

export interface WordFileMenuItem {
  icon: string
  label: string
  /** The line under the label: what it does, or why it is off. */
  sub?: string
  disabled?: boolean
  onSelect: () => void
}

export function WordFileMenu({ trigger, items, label }: {
  /** The button that opens it (rendered as the trigger, `asChild`). */
  trigger: ReactNode
  items: WordFileMenuItem[]
  /** The menu's accessible name. */
  label: string
}) {
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>{trigger}</DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          aria-label={label}
          className="z-50 w-60 bg-surface-container-lowest rounded-xl border border-outline-variant shadow-[0_4px_16px_rgba(4,22,39,.14)] p-1"
        >
          {items.map((item) => (
            <DropdownMenu.Item
              key={item.label}
              disabled={item.disabled}
              onSelect={item.onSelect}
              className={cn(
                'flex items-start gap-2 px-2.5 py-2 rounded-lg outline-none select-none text-xs leading-4',
                item.disabled ? 'text-outline cursor-not-allowed' : 'text-on-surface cursor-pointer data-[highlighted]:bg-surface-container-low',
              )}
            >
              <Icon name={item.icon} size={16} className={cn('flex-shrink-0', item.disabled ? 'text-outline-variant' : 'text-secondary')} />
              <span className="min-w-0">
                <span className="block font-medium">{item.label}</span>
                {/* The space keeps the label and its line apart in the item's accessible name. */}
                {item.sub && <>{' '}<span className="block mt-px text-caption text-outline leading-[15px]">{item.sub}</span></>}
              </span>
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
