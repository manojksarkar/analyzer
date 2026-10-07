import { useEffect, useRef, useState } from 'react'

/** A number that counts up to `target` over `ms` (ease-out), from where it was: the Overview's
 *  approval gauge, as the mockups'. With reduced motion -- or no `matchMedia`, as in the tests --
 *  it is the target at once. */
export function useCountUp(target: number, ms = 800): number {
  const still = typeof window === 'undefined' || typeof window.matchMedia !== 'function'
    || window.matchMedia('(prefers-reduced-motion: reduce)').matches
  const [shown, setShown] = useState(() => (still ? target : 0))
  const last = useRef(shown)
  useEffect(() => {
    if (still) return
    const from = last.current
    let t0: number | null = null           // timed from the first frame: its clock, not performance.now()'s
    let frame = 0
    const step = (now: number) => {
      t0 ??= now
      const k = Math.min(Math.max((now - t0) / ms, 0), 1)
      last.current = Math.round(from + (target - from) * (1 - (1 - k) ** 3))
      setShown(last.current)
      if (k < 1) frame = requestAnimationFrame(step)
    }
    frame = requestAnimationFrame(step)
    return () => cancelAnimationFrame(frame)
  }, [target, ms, still])
  return still ? target : shown
}
