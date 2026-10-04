import type { CompareBlock, CompareDocumentDiff, CompareRichSection, DiffMark, DiffType, Version } from '../../types'

export type TreeMode = 'diff' | 'all'

/* ─── Diff-type chip styling ───
   `sign` says the kind of change without its colour (+ added, ~ changed, − removed): colour alone
   is lost on a colour-blind reader, a grey-scale print, a screen reader. */
export const DIFF_BADGE: Record<DiffType, { label: string; sign: string; cls: string; text: string; dot: string }> = {
  added:     { label: 'added',     sign: '+', cls: 'text-on-tertiary-container bg-[rgba(0,165,114,.1)]', text: 'text-on-tertiary-container', dot: 'bg-on-tertiary-container' },
  changed:   { label: 'changed',   sign: '~', cls: 'text-secondary bg-secondary/10',                     text: 'text-secondary',             dot: 'bg-secondary' },
  removed:   { label: 'removed',   sign: '−', cls: 'text-error bg-error-container',                       text: 'text-error',                 dot: 'bg-error' },
  unchanged: { label: 'unchanged', sign: '',  cls: 'text-on-surface-variant bg-surface-container',        text: 'text-on-surface-variant',    dot: 'bg-outline-variant' },
}

/** A word or cell's change, in words and as a sign, beside its highlight colour. */
export const MARK_MEANING: Record<Exclude<DiffMark, 'none'>, { label: string; sign: string }> = {
  add:    { label: 'added',   sign: '+' },
  del:    { label: 'removed', sign: '−' },
  change: { label: 'changed', sign: '~' },
}

/** One table row's change for its marker: the row's own mark, else `change` when any cell of it
 *  changed, else none. */
export function rowChange(rowMark: DiffMark | undefined, cellMarks: DiffMark[] | undefined): DiffMark {
  if (rowMark && rowMark !== 'none') return rowMark
  return (cellMarks ?? []).some((m) => m !== 'none') ? 'change' : 'none'
}

/* ─── Section accent (left stripe at the gutter) by the kind of change ─── */
export function sectionAccent(diffType: DiffType): string {
  if (diffType === 'unchanged') return ''
  if (diffType === 'added')   return 'border-l-[3px] border-l-on-tertiary-container bg-[rgba(0,165,114,.03)]'
  if (diffType === 'removed') return 'border-l-[3px] border-l-error bg-error-container/30'
  return 'border-l-[3px] border-l-secondary bg-surface-container-low'
}

/** How a version is named to the compare routes: its id (the API resolves an id, a tag or a
 *  commit). Never its commit alone: two versions of one commit are two versions. */
export function versionRef(v: Version | undefined): string | undefined {
  return v ? v.id ?? v.sha : undefined
}

/** The versions the current one can be compared with: every one older than it (the list is
 *  newest first). */
export function olderVersions(versions: Version[] | undefined, current: Version | undefined): Version[] {
  if (!versions || !current) return []
  const key = versionRef(current)
  const idx = versions.findIndex((v) => versionRef(v) === key)
  return idx >= 0 ? versions.slice(idx + 1) : []
}

/**
 * The two versions compared: the Subbar's (`current`) and, as the reference, the older version
 * `reference` names (the page's `?ref=`), else the one just before it in the project's list
 * (newest first). Found by id, so a version made on the same commit as another is still its own.
 * No current version (a commit with no run) → nothing to compare.
 */
export function compareVersions(versions: Version[] | undefined, current: Version | undefined, reference?: string | null): {
  current?: Version
  baseline?: Version
} {
  if (!versions || !current) return { current }
  const older = olderVersions(versions, current)
  const picked = reference ? older.find((v) => versionRef(v) === reference) : undefined
  return { current, baseline: picked ?? older[0] }
}

/* ─── A unified, render-ready section for the two-pane diff ─── */
export interface PaneSection {
  key: string
  title: string
  number: string
  level: number
  diffType: DiffType
  sourceLabel: string
  /** rich blocks (mode 'rich') */
  current?: CompareBlock[]
  baseline?: CompareBlock[]
  /** flat markdown (mode 'flat') */
  currentText?: string
  baselineText?: string
}

/** Unify rich + flat diffs into one render-ready section list. */
export function paneSections(detail: CompareDocumentDiff | undefined): PaneSection[] {
  if (!detail) return []
  if (detail.mode === 'rich') {
    return detail.sections.map((s: CompareRichSection) => ({
      key: s.id,
      title: s.title,
      number: s.number,
      level: s.level,
      diffType: s.diffType,
      sourceLabel: s.source.artifact,
      current: s.currentBlocks,
      baseline: s.baselineBlocks,
    }))
  }
  return detail.flatSections.map((s) => ({
    key: s.key,
    title: s.title,
    number: '',
    level: 1,
    diffType: s.diffType,
    sourceLabel: 'Interface table',
    currentText: s.currentContent,
    baselineText: s.baselineContent,
  }))
}
