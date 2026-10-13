import { useEffect, useRef, useState, type ReactNode } from 'react'
import { cn } from '../../lib/cn'

/**
 * A box that scrolls sideways when what it holds is wider (a document's table). Only then is it a
 * Tab stop, so the arrow keys can scroll it; a table that fits adds no stop.
 */
export function ScrollX({ className, children }: { className?: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [scrolls, setScrolls] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => setScrolls(el.scrollWidth > el.clientWidth + 1)
    check()
    if (typeof ResizeObserver === 'undefined') return
    const watch = new ResizeObserver(check)
    watch.observe(el)
    return () => watch.disconnect()
  }, [])
  return (
    <div
      ref={ref}
      className={cn('overflow-x-auto', className)}
      {...(scrolls ? { tabIndex: 0, role: 'group', 'aria-label': 'Table, scrolls sideways' } : {})}
    >
      {children}
    </div>
  )
}
