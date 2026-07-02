export interface BrandMarkProps {
  /** px width/height; the mark is square. Defaults to 32. */
  size?: number
  className?: string
}

/**
 * The ArtiFex product mark: ‹ A ✦ › — code angle-brackets framing a half-drawn
 * "A" whose right leg dissolves into an AI spark. No background/container; every
 * stroke & fill is `currentColor`, so callers set the color via a text-* class
 * (e.g. `text-secondary` on light surfaces, `text-white` on dark). Single source
 * of truth for the logo glyph; pairs with `constants/branding.ts` for the wordmark.
 */
export function BrandMark({ size = 32, className }: BrandMarkProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      {/* code angle brackets ‹ › (pushed out for breathing room) */}
      <g stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 8.5 2 16l3 7.5" />
        <path d="M27 8.5 30 16l-3 7.5" />
      </g>
      {/* half "A" — left slash + crossbar; the right leg is completed by the spark */}
      <g stroke="currentColor" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round">
        <path d="M13.6 7 9.2 24" />
        <path d="M11 17.8h6.2" />
      </g>
      {/* AI spark (the dissolving right leg) */}
      <path
        fill="currentColor"
        d="M19.8 18.6C19.8 20.7 20.9 21.8 23 21.8 20.9 21.8 19.8 22.9 19.8 25 19.8 22.9 18.7 21.8 16.6 21.8 18.7 21.8 19.8 20.7 19.8 18.6Z"
      />
    </svg>
  )
}
