import { forwardRef, type ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'outline'
export type ButtonSize = 'sm' | 'md' | 'lg' | 'icon'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:   'bg-secondary text-white hover:bg-[#0046a0] focus-visible:ring-secondary disabled:bg-secondary/40',
  secondary: 'bg-surface-container text-on-surface hover:bg-surface-container-low border border-outline-variant focus-visible:ring-secondary',
  ghost:     'text-on-surface-variant hover:bg-surface-container hover:text-on-surface focus-visible:ring-secondary',
  danger:    'bg-error text-white hover:bg-[#960d0d] focus-visible:ring-error disabled:bg-error/40',
  outline:   'border border-outline-variant text-on-surface hover:bg-surface-container focus-visible:ring-secondary',
}

const sizeClasses: Record<ButtonSize, string> = {
  sm:   'h-7 px-3 text-xs gap-1',
  md:   'h-9 px-4 text-sm gap-1.5',
  lg:   'h-11 px-5 text-sm gap-2',
  icon: 'h-8 w-8 p-0',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = 'primary', size = 'md', loading, disabled, children, ...props }, ref) => (
    <button
      ref={ref}
      disabled={disabled || loading}
      aria-busy={loading}
      className={cn(
        'inline-flex items-center justify-center rounded-lg font-semibold transition-colors',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1',
        'disabled:pointer-events-none disabled:opacity-50',
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    >
      {loading && (
        <svg className="animate-spin -ml-0.5 h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" aria-hidden>
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      )}
      {children}
    </button>
  )
)
Button.displayName = 'Button'
