import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  hint?: string
  leadingIcon?: string
  trailingIcon?: string
  onTrailingClick?: () => void
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, label, error, hint, leadingIcon, trailingIcon, onTrailingClick, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-')

    return (
      <div className="w-full">
        {label && (
          <label
            htmlFor={inputId}
            className="block mb-1.5 font-mono text-[11px] font-semibold text-on-surface-variant uppercase tracking-[0.08em]"
          >
            {label}
          </label>
        )}
        <div className="relative">
          {leadingIcon && (
            <span
              className="material-symbols-outlined pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-on-surface-variant"
              style={{ fontSize: 18 }}
              aria-hidden
            >
              {leadingIcon}
            </span>
          )}
          <input
            ref={ref}
            id={inputId}
            aria-invalid={!!error}
            aria-describedby={error ? `${inputId}-error` : hint ? `${inputId}-hint` : undefined}
            className={cn(
              'w-full h-10 rounded-xl border bg-surface-container-lowest text-sm text-on-surface placeholder:text-outline',
              'transition-colors focus:border-secondary',
              error ? 'border-error' : 'border-field',
              leadingIcon ? 'pl-9' : 'pl-3',
              trailingIcon ? 'pr-9' : 'pr-3',
              'disabled:bg-surface-container disabled:cursor-not-allowed disabled:opacity-60',
              className,
            )}
            {...props}
          />
          {trailingIcon && (
            <button
              type="button"
              onClick={onTrailingClick}
              className="absolute right-2 top-1/2 -translate-y-1/2 p-1 rounded-lg text-on-surface-variant hover:text-on-surface transition-colors"
              tabIndex={onTrailingClick ? 0 : -1}
              aria-label={onTrailingClick ? 'Toggle' : undefined}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden>{trailingIcon}</span>
            </button>
          )}
        </div>
        {error && (
          <p id={`${inputId}-error`} role="alert" className="mt-1 text-xs text-error flex items-center gap-1">
            <span className="material-symbols-outlined" style={{ fontSize: 12 }} aria-hidden>error</span>
            {error}
          </p>
        )}
        {!error && hint && (
          <p id={`${inputId}-hint`} className="mt-1 text-xs text-on-surface-variant">{hint}</p>
        )}
      </div>
    )
  }
)
Input.displayName = 'Input'
