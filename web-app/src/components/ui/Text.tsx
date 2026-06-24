import type { ElementType, HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

/**
 * Typography roles seen across the designs. Each variant sets font family +
 * size (+ a sensible default weight/tracking); colour and weight overrides go
 * through `className` (twMerge lets the caller win). Sizes map to the
 * `@theme` typography tokens in index.css.
 */
export type TextVariant =
  | 'label'    // mono 10px, uppercase, tracked — field labels, sha/count chips
  | 'caption'  // sans 11px, muted — authors, dates, sub-labels
  | 'mono'     // mono 12px — code-ish inline text, member names
  | 'body'     // sans 13px — descriptions, row content
  | 'title'    // sans 15px, semibold — sub-section titles
  | 'heading'  // sans 18px, semibold — card/panel titles

const variants: Record<TextVariant, string> = {
  label:   'font-mono text-label font-medium uppercase tracking-[0.06em]',
  caption: 'text-caption text-on-surface-variant',
  mono:    'font-mono text-xs',
  body:    'text-body',
  title:   'text-title font-semibold',
  heading: 'text-lg font-semibold',
}

interface TextProps extends HTMLAttributes<HTMLElement> {
  /** element to render — defaults to span */
  as?: ElementType
  variant?: TextVariant
}

export function Text({ as: Tag = 'span', variant = 'body', className, ...rest }: TextProps) {
  return <Tag className={cn(variants[variant], className)} {...rest} />
}
