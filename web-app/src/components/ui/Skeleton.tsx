import { Fragment, type CSSProperties } from 'react'
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

/* Dashboard placeholder — mirrors ProjectDetailPage's KPI strip + two-column body
   so swapping in real content causes minimal layout shift. */
export function DashboardSkeleton() {
  return (
    <>
      {/* KPI strip */}
      <div className="mb-6 grid grid-cols-[2fr_1fr_1fr] gap-4 items-stretch">
        <Skeleton className="h-[156px]" />
        <Skeleton className="h-[156px]" />
        <Skeleton className="h-[156px]" />
      </div>
      {/* Body: wide docs card + sidebar */}
      <div className="flex gap-6 items-stretch">
        <div className="flex-1 min-w-0 flex flex-col gap-4">
          <Skeleton className="h-72" />
          <Skeleton className="h-40" />
        </div>
        <div className="w-[300px] flex-shrink-0 flex flex-col gap-4">
          <Skeleton className="h-44" />
          <Skeleton className="h-32" />
        </div>
      </div>
    </>
  )
}

/* Compare detail placeholder — a couple of two-column section blocks for the
   right-hand pane while a document's diff loads. */
export function CompareSectionSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div className="grid grid-cols-2 items-stretch">
      {Array.from({ length: rows }).map((_, i) => (
        <Fragment key={i}>
          <div className="bg-white border-r border-b border-outline-variant/60 px-8 py-6 space-y-3">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-5/6" />
          </div>
          <div className="bg-white border-b border-outline-variant/60 px-8 py-6 space-y-3">
            <Skeleton className="h-5 w-1/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/6" />
          </div>
        </Fragment>
      ))}
    </div>
  )
}
