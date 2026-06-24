import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/cn'

/**
 * The design's standard panel chrome: white surface, hairline border, rounded.
 * Padding/overflow are left to the caller since panels vary (headered cards,
 * scroll regions, list containers).
 */
export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('bg-surface-container-lowest border border-outline-variant rounded-xl', className)}
      {...rest}
    />
  )
}
