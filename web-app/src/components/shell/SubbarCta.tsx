import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

/**
 * The Subbar's right-hand slot holds the page's primary action (the mockups' CTA: Overview
 * "Run Analysis", Documents "Download All", …). The Subbar is rendered by ProjectLayout, above
 * the page's <Outlet>, so a page renders its action through <SubbarCta> into that slot.
 */
const SlotContext = createContext<HTMLElement | null>(null)

export function SubbarCtaProvider({ slot, children }: { slot: HTMLElement | null; children: ReactNode }) {
  return <SlotContext.Provider value={slot}>{children}</SlotContext.Provider>
}

/** Render `children` as the current page's Subbar action. */
export function SubbarCta({ children }: { children: ReactNode }) {
  const slot = useContext(SlotContext)
  return slot ? createPortal(children, slot) : null
}
