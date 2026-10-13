import * as CheckboxPrimitive from '@radix-ui/react-checkbox'
import { cn } from '../../lib/cn'

interface CheckboxProps {
  checked: boolean | 'indeterminate'
  onCheckedChange: (v: boolean | 'indeterminate') => void
  label?: string
  disabled?: boolean
  className?: string
}

export function Checkbox({ checked, onCheckedChange, label, disabled, className }: CheckboxProps) {
  const id = label ? `cb-${label.toLowerCase().replace(/\s+/g, '-')}` : undefined

  return (
    <div className={cn('flex items-center gap-2', className)}>
      <CheckboxPrimitive.Root
        id={id}
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        className={cn(
          'h-4 w-4 rounded border border-field bg-surface-container-lowest flex-shrink-0',
          'transition-colors',
          'data-[state=checked]:bg-action data-[state=checked]:border-action',
          'data-[state=indeterminate]:bg-action data-[state=indeterminate]:border-action',
          'disabled:cursor-not-allowed disabled:opacity-50',
        )}
      >
        <CheckboxPrimitive.Indicator className="flex items-center justify-center text-white">
          {checked === 'indeterminate'
            ? <span className="material-symbols-outlined" style={{ fontSize: 12 }} aria-hidden>remove</span>
            : <span className="material-symbols-outlined" style={{ fontSize: 12 }} aria-hidden>check</span>
          }
        </CheckboxPrimitive.Indicator>
      </CheckboxPrimitive.Root>
      {label && (
        <label htmlFor={id} className="text-sm text-on-surface cursor-pointer select-none">
          {label}
        </label>
      )}
    </div>
  )
}
