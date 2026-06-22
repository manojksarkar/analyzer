import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { cn } from '../../lib/cn'

export const Dropdown = DropdownMenu.Root
export const DropdownTrigger = DropdownMenu.Trigger

interface DropdownItem {
  label: string
  icon?: string
  variant?: 'default' | 'danger'
  onClick: () => void
  disabled?: boolean
}

interface DropdownContentProps {
  items: DropdownItem[]
  align?: 'start' | 'end' | 'center'
}

export function DropdownContent({ items, align = 'end' }: DropdownContentProps) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        align={align}
        sideOffset={4}
        className={cn(
          'z-50 min-w-[160px] bg-white rounded-xl border border-outline-variant',
          'shadow-[0_4px_24px_rgba(4,22,39,.12)] p-1',
          'animate-in fade-in-0 zoom-in-95',
        )}
      >
        {items.map((item) => (
          <DropdownMenu.Item
            key={item.label}
            disabled={item.disabled}
            onSelect={item.onClick}
            className={cn(
              'flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm cursor-pointer',
              'select-none outline-none transition-colors',
              item.variant === 'danger'
                ? 'text-error data-[highlighted]:bg-error/10'
                : 'text-on-surface data-[highlighted]:bg-surface-container',
              item.disabled && 'opacity-40 pointer-events-none',
            )}
          >
            {item.icon && (
              <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden>{item.icon}</span>
            )}
            {item.label}
          </DropdownMenu.Item>
        ))}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  )
}
