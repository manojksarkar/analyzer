import type { CSSProperties } from 'react'
import { cn } from '../../lib/cn'

interface SkeletonProps {
  className?: string
  style?: CSSProperties
}

export function Skeleton({ className, style }: SkeletonProps) {
  return (
    <div
      className={cn('animate-pulse rounded-lg bg-surface-container', className)}
      style={style}
      aria-hidden
    />
  )
}

export function TableSkeleton({ rows = 5, cols = 5 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-0">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3 border-b border-outline-variant">
          {Array.from({ length: cols }).map((_, j) => (
            <Skeleton key={j} className="h-4 flex-1" style={{ maxWidth: j === 0 ? 180 : j === cols - 1 ? 80 : undefined } as React.CSSProperties} />
          ))}
        </div>
      ))}
    </div>
  )
}
