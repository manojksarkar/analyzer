import { clsx, type ClassValue } from 'clsx'
import { extendTailwindMerge } from 'tailwind-merge'

// The theme's own font sizes (index.css @theme `--text-*`). tailwind-merge does not read the
// theme, so without them it took `text-caption` for a COLOUR: of `text-caption text-outline` it
// kept only the last, and small labels across the app lost their size (or, the other way round,
// their colour).
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ['micro', 'label', 'caption', 'body', 'title'] } },
})

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}
