import { cn } from '../../lib/cn'

export interface IconProps {
  /** Material Symbols Outlined glyph name, e.g. "description" */
  name: string
  /** px font-size; defaults to 20 (the Material Symbols base size) */
  size?: number
  /** render the filled glyph variant */
  fill?: boolean
  className?: string
  /** accessible label; when omitted the icon is treated as decorative (aria-hidden) */
  label?: string
}

/**
 * Material Symbols icon. This is the *sanctioned* home for glyph sizing —
 * everywhere else, icon size comes through `size` rather than an inline style.
 */
export function Icon({ name, size = 20, fill, className, label }: IconProps) {
  return (
    <span
      className={cn('material-symbols-outlined', fill && 'sym-fill', className)}
      // eslint-disable-next-line no-restricted-syntax -- Icon encapsulates glyph sizing; callers pass `size`
      style={size === 20 ? undefined : { fontSize: size }}
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? 'img' : undefined}
    >
      {name}
    </span>
  )
}
