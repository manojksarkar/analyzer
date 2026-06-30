/**
 * Presentation helpers shared by the API mappers.
 *
 * The backend returns ISO-8601 timestamps and raw identifiers; the UI wants
 * human strings ("Jun 15, 2026", "2h ago") and stable per-user avatar colors.
 * Keeping this logic here means the mapper layer stays declarative.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-06-15T…" → "Jun 15, 2026". Returns null for nullish input. */
export function formatDate(iso?: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return `${MONTHS[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`
}

/** "Jun 15" (no year) — used in compact table cells. */
export function formatShortDate(iso?: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return `${MONTHS[d.getMonth()]} ${d.getDate()}`
}

/** ISO timestamp → "just now" / "5m ago" / "2h ago" / "3d ago" / date. */
export function relativeTime(iso?: string | null): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const secs = Math.floor((Date.now() - then) / 1000)
  if (secs < 45) return 'just now'
  const mins = Math.floor(secs / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}w ago`
  return formatDate(iso) ?? '—'
}

/** First 7 chars of a commit sha (mirrors `git rev-parse --short`). */
export function shortSha(sha?: string | null): string {
  return (sha ?? '').slice(0, 7)
}

/**
 * Deterministic avatar palette derived from a stable seed (user id / initials).
 * Mirrors the hand-picked colors the mock data used so the UI looks identical.
 */
const AVATAR_PALETTE: { bg: string; text: string }[] = [
  { bg: '#e0f2fe', text: '#0369a1' },
  { bg: '#dbeafe', text: '#1e40af' },
  { bg: '#fce7f3', text: '#be185d' },
  { bg: '#fef9c3', text: '#92400e' },
  { bg: '#f3e8ff', text: '#7c3aed' },
  { bg: '#fff7ed', text: '#c2410c' },
  { bg: '#ecfdf5', text: '#065f46' },
  { bg: '#e0f2ff', text: '#0058be' },
]

export function avatarPalette(seed: string): { bg: string; text: string } {
  let hash = 0
  for (let i = 0; i < seed.length; i++) hash = (hash * 31 + seed.charCodeAt(i)) >>> 0
  return AVATAR_PALETTE[hash % AVATAR_PALETTE.length]
}
