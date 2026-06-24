import * as SelectPrimitive from '@radix-ui/react-select'
import { cn } from '../../lib/cn'

interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

interface SelectProps {
  value: string
  onValueChange: (v: string) => void
  options: SelectOption[]
  placeholder?: string
  label?: string
  error?: string
  disabled?: boolean
  className?: string
}

export function Select({ value, onValueChange, options, placeholder, label, error, disabled, className }: SelectProps) {
  const id = label?.toLowerCase().replace(/\s+/g, '-')
  return (
    <div className={cn('w-full', className)}>
      {label && (
        <label
          id={id}
          className="block mb-1.5 font-mono text-[11px] font-semibold text-on-surface-variant uppercase tracking-[0.08em]"
        >
          {label}
        </label>
      )}
      <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
        <SelectPrimitive.Trigger
          aria-labelledby={id}
          aria-invalid={!!error}
          className={cn(
            'flex w-full h-10 items-center justify-between gap-2 rounded-xl border bg-white px-3',
            'text-sm text-on-surface transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-secondary focus:border-secondary',
            'disabled:cursor-not-allowed disabled:opacity-50',
            error ? 'border-error' : 'border-outline-variant',
          )}
        >
          <SelectPrimitive.Value placeholder={<span className="text-on-surface-variant/60">{placeholder}</span>} />
          <SelectPrimitive.Icon>
            <span className="material-symbols-outlined text-on-surface-variant" style={{ fontSize: 18 }} aria-hidden>expand_more</span>
          </SelectPrimitive.Icon>
        </SelectPrimitive.Trigger>
        <SelectPrimitive.Portal>
          <SelectPrimitive.Content
            position="popper"
            sideOffset={4}
            className={cn(
              'z-50 min-w-[var(--radix-select-trigger-width)] rounded-xl border border-outline-variant bg-white p-1',
              'shadow-[0_4px_24px_rgba(4,22,39,.12)]',
              'animate-in fade-in-0 zoom-in-95',
            )}
          >
            <SelectPrimitive.Viewport>
              {options.map((opt) => (
                <SelectPrimitive.Item
                  key={opt.value}
                  value={opt.value}
                  disabled={opt.disabled}
                  className={cn(
                    'flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-on-surface',
                    'cursor-pointer select-none outline-none',
                    'data-[highlighted]:bg-surface-container',
                    'data-[disabled]:opacity-40 data-[disabled]:pointer-events-none',
                  )}
                >
                  <SelectPrimitive.ItemText>{opt.label}</SelectPrimitive.ItemText>
                  <SelectPrimitive.ItemIndicator className="ml-auto">
                    <span className="material-symbols-outlined text-secondary" style={{ fontSize: 14 }} aria-hidden>check</span>
                  </SelectPrimitive.ItemIndicator>
                </SelectPrimitive.Item>
              ))}
            </SelectPrimitive.Viewport>
          </SelectPrimitive.Content>
        </SelectPrimitive.Portal>
      </SelectPrimitive.Root>
      {error && (
        <p role="alert" className="mt-1 text-xs text-error flex items-center gap-1">
          <span className="material-symbols-outlined" style={{ fontSize: 12 }} aria-hidden>error</span>
          {error}
        </p>
      )}
    </div>
  )
}
