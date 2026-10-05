import { useEffect, useState } from 'react'

/** The id of the last section whose top has scrolled past the top of `el` (plus a margin for
 *  the sticky edit bar), among `ids` in document order. Sections render as `sec-<id>`. Takes the
 *  element itself (from a callback ref), so it attaches once the canvas exists. */
export function useScrollSpy(el: HTMLElement | null, ids: string[], offset = 120): string | null {
  const [active, setActive] = useState<string | null>(null)
  useEffect(() => {
    if (!el || !ids.length) return
    let frame = 0
    const measure = () => {
      frame = 0
      const top = el.getBoundingClientRect().top + offset
      let current: string | null = ids[0]
      for (const id of ids) {
        const sec = document.getElementById(`sec-${id}`)
        if (!sec) continue
        if (sec.getBoundingClientRect().top <= top) current = id
        else break
      }
      setActive(current)
    }
    const onScroll = () => { if (!frame) frame = requestAnimationFrame(measure) }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => {
      el.removeEventListener('scroll', onScroll)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [el, ids, offset])
  return active
}
