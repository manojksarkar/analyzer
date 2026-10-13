import { describe, expect, it } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

/* Accessibility guards that need no browser (WCAG 2.2 AA; the rules are the ui-dev skill's §8).
   Two things regress silently: a token's value, and a class that undoes a shared rule. This file
   checks both -- the colour tokens' contrast in the light and the dark theme, and the source for the
   patterns that failed before 2026-10-13. It cannot see a rendered page: a new screen still gets a
   Tab walk and an axe run in both themes. */

const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const CSS = readFileSync(join(SRC, 'index.css'), 'utf8')

// ── the tokens of each theme ──────────────────────────────────────────────────────────────────
function block(css: string, opener: string): string {
  const start = css.indexOf(opener)
  if (start < 0) throw new Error(`index.css has no ${opener}`)
  return css.slice(css.indexOf('{', start) + 1, css.indexOf('\n}', start))
}
function tokens(body: string): Record<string, string> {
  const out: Record<string, string> = {}
  for (const m of body.matchAll(/--color-([\w-]+):\s*(#[0-9a-fA-F]{6})\b/g)) out[m[1]] = m[2].toLowerCase()
  return out
}
const LIGHT = tokens(block(CSS, '@theme'))
const DARK = { ...LIGHT, ...tokens(block(CSS, ':root[data-theme="dark"]')) }
const THEMES: [string, Record<string, string>][] = [['light', LIGHT], ['dark', DARK]]

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const v = parseInt(hex.slice(i, i + 2), 16) / 255
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const WHITE = '#ffffff'
/** The surfaces a page is made of: a card, the page behind it, a table's header row. */
const SURFACES = ['surface-container-lowest', 'surface', 'surface-container-low']
/** Colours used as text. */
const TEXT = ['on-surface', 'on-surface-variant', 'outline', 'faint', 'secondary', 'error', 'success',
  'on-tertiary-container', 'warn', 'caution', 'violet', 'state-done', 'state-warn']

describe.each(THEMES)('colour tokens, %s theme', (_name, t) => {
  const pair = (fg: string, bg: string) => contrast(fg === 'white' ? WHITE : t[fg], t[bg])

  it.each(TEXT)('text in `%s` reads on every surface (4.5:1)', (fg) => {
    for (const bg of SURFACES) expect(pair(fg, bg), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
  })

  it('a field border and the focus ring stand out from every surface (3:1)', () => {
    for (const bg of SURFACES) {
      expect(pair('field', bg), `field on ${bg}`).toBeGreaterThanOrEqual(3)
      expect(pair('focus', bg), `focus on ${bg}`).toBeGreaterThanOrEqual(3)
    }
  })

  it('white text reads on the fills that carry it (4.5:1)', () => {
    for (const bg of ['action', 'secondary-container', 'inverse', 'selected', 'hero']) {
      expect(pair('white', bg), `white on ${bg}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('`on-status` reads on the status fills (4.5:1)', () => {
    for (const bg of ['error', 'on-tertiary-container', 'outline']) {
      expect(pair('on-status', bg), `on-status on ${bg}`).toBeGreaterThanOrEqual(4.5)
    }
  })

  it('the sign-in brand panel: its text 4.5:1, its ticks 3:1', () => {
    expect(pair('on-hero', 'hero')).toBeGreaterThanOrEqual(4.5)
    expect(pair('hero-accent', 'hero')).toBeGreaterThanOrEqual(4.5)
    expect(pair('hero-ok', 'hero')).toBeGreaterThanOrEqual(3)
    expect(pair('on-primary-container', 'primary-container')).toBeGreaterThanOrEqual(4.5)
  })
})

// ── the source ────────────────────────────────────────────────────────────────────────────────
function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === '__tests__' || name === 'test' ? [] : sources(path)
    return /\.tsx?$/.test(name) && !name.endsWith('.d.ts') ? [path] : []
  })
}
const FILES = sources(SRC).map((path) => ({ rel: relative(SRC, path).replace(/\\/g, '/'), text: readFileSync(path, 'utf8') }))

/** Every line of every source file that `test` matches, as `file:line: text`. */
function lines(test: (line: string) => boolean): string[] {
  return FILES.flatMap(({ rel, text }) =>
    text.split('\n').flatMap((line, i) => (test(line) ? [`${rel}:${i + 1}: ${line.trim().slice(0, 120)}`] : [])))
}

/** The JSX opening tags of the given elements, each as written (braces, quotes and regex literals
 *  followed: a `>` or a quote inside one of them does not end the tag). */
function openingTags(text: string, names: string[]): string[] {
  const out: string[] = []
  for (const m of text.matchAll(new RegExp(`<(?:${names.join('|')})\\b`, 'g'))) {
    let depth = 0
    let quote = ''
    let i = m.index
    for (; i < text.length; i++) {
      const c = text[i]
      if (quote) { if (c === '\\') i++; else if (c === quote) quote = '' }
      else if (c === '"' || c === "'" || c === '`') quote = c
      else if (c === '/' && depth > 0 && /[(,=:[!&|?{};]\s*$/.test(text.slice(Math.max(0, i - 12), i))) {
        // a regex literal (`.replace(/`/g, '')`): to its closing slash
        for (i++; i < text.length && text[i] !== '/'; i++) if (text[i] === '\\') i++
      }
      else if (c === '{') depth++
      else if (c === '}') depth--
      else if (c === '>' && depth === 0) break
    }
    out.push(text.slice(m.index, i + 1))
  }
  return out
}

describe('the source keeps the shared rules', () => {
  it('nothing a person reads is under 11px', () => {
    const small = (px: string) => parseFloat(px) < 11
    expect(lines((l) => [...l.matchAll(/text-\[([\d.]+)px\]/g)].some((m) => small(m[1])))).toEqual([])
    // index.css's own classes: `font-size: 10px`, `font: 600 10px/16px ...`
    const css = [...CSS.matchAll(/font(?:-size)?:\s*(?:[\w-]+\s+)*?([\d.]+)px/g)].filter((m) => small(m[1])).map((m) => m[0])
    expect(css).toEqual([])
  })

  it('no component styles its own focus: the one ring is in index.css', () => {
    expect(lines((l) => /(?:focus|focus-visible):(?:outline-none|ring\b|ring-)/.test(l))).toEqual([])
    // `outline-none` only on a borderless input inside a bordered box, which shows the ring instead
    expect(lines((l) => /(?<![\w:-])outline-none(?![\w-])/.test(l) && !/bg-transparent/.test(l))).toEqual([])
  })

  it('text is not faded: quiet text is `text-outline`', () => {
    expect(lines((l) => /(?<![\w-])text-[a-z-]+\/\d+/.test(l))).toEqual([])
    // the divider colour as text only for a divider glyph, or for something that is switched off
    expect(lines((l) => /(?<![\w-])text-outline-variant(?![\w-])/.test(l) && !/aria-hidden|disabled|cursor-not-allowed/.test(l))).toEqual([])
  })

  it('white text sits on `bg-action`, not on `bg-secondary` (two colours in dark)', () => {
    expect(lines((l) => /(?<![\w-])bg-secondary(?![\w/-])/.test(l) && /(?<![\w:-])(?:text-white|text-on-secondary)(?![\w-])/.test(l))).toEqual([])
  })

  it('a field is not bordered in the divider colour (3:1 needs `border-field`)', () => {
    const faint = FILES.flatMap(({ rel, text }) => openingTags(text, ['input', 'select', 'textarea'])
      .filter((tag) => /(?<![\w:-])border-outline-variant(?![\w/-])/.test(tag))
      .map((tag) => `${rel}: ${tag.replace(/\s+/g, ' ').slice(0, 100)}`))
    expect(faint).toEqual([])
  })
})
