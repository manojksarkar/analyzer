import type { Document, ExportReadiness, OutOfDateFile, VersionWriter } from '../types'

/* Word file updates: the rules every screen shares (docs/design/WORD_FILE_UPDATES.md; the words
   are the mockup's, docs/ui-mockups/documents.html). States: Up to date · Out of date (why) ·
   Updating… · Update failed (Try again) · Approved. One update at a time per version, no queue;
   none while a run holds the version. The server enforces every rule; these say it first.
   Wording: one plain verb per button, one short sentence per message; details go in a tooltip. */

const ACTIVE = ['queued', 'running']

export const plural = (n: number, w: string): string => `${n} ${w}${n === 1 ? '' : 's'}`
export const cap = (s: string): string => (s ? s[0].toUpperCase() + s.slice(1) : s)
/** A sentence's end: no doubled full stop when the server already wrote one. */
const sentence = (s: string): string => `${cap(s.trim().replace(/[.\s]+$/, ''))}.`

/** A component's name from its layer-qualified id, when no document names it: the part after the
 *  layer (`Layer1.Brake-Controller` → `Brake-Controller`), as the server's own fallback. */
export function componentFallbackName(id: string): string {
  const dot = id.indexOf('.')
  return dot >= 0 && dot < id.length - 1 ? id.slice(dot + 1) : id
}

/** Names components by their documents (`group` → `name`), else by their id. */
export function componentNamer(
  docs: Pick<Document, 'group' | 'name'>[] = [], files: Pick<OutOfDateFile, 'component' | 'name'>[] = [],
): (id: string) => string {
  const names = new Map<string, string>()
  for (const f of files) names.set(f.component, f.name)
  for (const d of docs) if (d.group) names.set(d.group, d.name)
  return (id) => names.get(id) ?? componentFallbackName(id)
}

/** Components by name, kept short: "Brake Controller", "Brake Controller and HVAC Ctrl", "3 components"
 *  (`these`: "these 3 components"). */
export function compNames(names: string[], these = false): string {
  const cs = [...new Set(names)]
  if (cs.length === 0) return 'the Word files'
  if (cs.length === 1) return cs[0]
  if (cs.length === 2) return `${cs[0]} and ${cs[1]}`
  return `${these ? 'these ' : ''}${cs.length} components`
}

/** A Word file as the screens list it: "Brake Controller (SWE.3)". */
export const fileLabel = (f: Pick<OutOfDateFile, 'name' | 'docType'>): string => `${f.name} (${f.docType})`

/** Why a Word file is out of date, short: "2 corrections not in it", "HAL_LAYER added since", or
 *  both. `brief`: the Review tab's "Out of date (2 corrections)". */
export function outOfDateWhy(f: Pick<OutOfDateFile, 'why' | 'corrections' | 'pictures' | 'layer'>, brief = false): string {
  const parts: string[] = []
  if (f.why.includes('corrections')) {
    parts.push((f.corrections ? plural(f.corrections, 'correction') : 'corrections') + (brief ? '' : ' not in it'))
  }
  if (f.why.includes('layerAdded')) parts.push(`${f.layer ?? 'a layer'} added${brief ? '' : ' since'}`)
  if (f.why.includes('pictures')) {
    parts.push((f.pictures ? plural(f.pictures, 'picture') : 'pictures') + (brief ? '' : ' being drawn'))
  }
  return parts.join(', ')
}

/** Why several Word files are out of date, counted once per component: "3 corrections, HAL_LAYER
 *  added since" (a component's SWE.3 and SWE.4 print the same corrections). */
export function reasonsOf(files: OutOfDateFile[]): string {
  const byComp = new Map<string, OutOfDateFile>()
  for (const f of files) {
    const seen = byComp.get(f.component)
    byComp.set(f.component, seen ? {
      ...seen,
      why: [...new Set([...seen.why, ...f.why])],
      corrections: Math.max(seen.corrections, f.corrections),
      pictures: Math.max(seen.pictures, f.pictures),
      layer: seen.layer ?? f.layer,
    } : f)
  }
  const comps = [...byComp.values()]
  const corrections = comps.reduce((a, f) => a + (f.why.includes('corrections') ? f.corrections : 0), 0)
  const pictures = comps.reduce((a, f) => a + (f.why.includes('pictures') ? f.pictures : 0), 0)
  const layers = [...new Set(comps.filter((f) => f.why.includes('layerAdded')).map((f) => f.layer ?? 'a layer'))]
  return [
    corrections ? plural(corrections, 'correction') : '',
    layers.length ? `${layers.join(', ')} added since` : '',
    pictures ? `${plural(pictures, 'picture')} being drawn` : '',
  ].filter(Boolean).join(', ')
}

/** The distinct components of some files, in order. */
export const componentsOf = (files: Pick<OutOfDateFile, 'component'>[]): string[] =>
  [...new Set(files.map((f) => f.component))]

/** The not-approved documents whose Word file is out of date. An API from before this contract
 *  says only `stale` (and `staleComponents`): then every not-approved document of a stale
 *  component, reason unknown ("corrections not in it"). */
export function outOfDateFiles(
  r: ExportReadiness | undefined,
  docs: Pick<Document, 'id' | 'group' | 'name' | 'process' | 'status'>[] = [],
): OutOfDateFile[] {
  if (!r) return []
  if (r.outOfDate) return r.outOfDate
  if (!r.stale) return []
  return docs
    .filter((d) => d.status !== 'approved' && !!d.group && (!r.staleComponents || r.staleComponents.includes(d.group)))
    .map((d) => ({
      documentId: d.id, component: d.group ?? '', name: d.name, docType: d.process, why: ['corrections'],
      corrections: 0, pictures: 0, layer: null, updating: false,
    }))
}

/** A15 (R9 for one document): its out-of-date entry, or undefined when its Word file is up to date.
 *  An API from before `outOfDate` answers the document question with `stale` and an empty
 *  `staleComponents` (a list it only fills for the version-wide question): `stale` is then this
 *  document's — never "up to date". An approved document is never out of date. */
export function ownOutOfDate(
  r: ExportReadiness | undefined, doc: Pick<Document, 'id' | 'group' | 'name' | 'process' | 'status'>,
): OutOfDateFile | undefined {
  if (!r || doc.status === 'approved') return undefined
  if (r.outOfDate) return r.outOfDate.find((f) => f.documentId === doc.id)
  if (!r.stale) return undefined
  return {
    documentId: doc.id, component: doc.group ?? '', name: doc.name, docType: doc.process, why: ['corrections'],
    corrections: 0, pictures: 0, layer: null, updating: false,
  }
}

/** An update a button asks for (the confirm dialog says what it writes, then starts it). */
export interface UpdateAsk {
  /** The components (ids) to update; null: every out-of-date one (an admin's *Update all*). */
  components: string[] | null
  /** An admin's *Rebuild all Word files*: every file, up to date or not. */
  rebuild?: boolean
  /** A download's *Corrected file*: this document's Word file (`docId`) — or Download all's
   *  *Corrected files*: the version's zip (`versionId`) — downloads once the update is done. */
  download?: { docId?: string; versionId?: string; fileName: string }
}

/* ── What runs ── */

/** The update running now (one per version): its components, whether it rebuilds every file, and
 *  how many components it has written. */
export interface RunningUpdate {
  jobId: string | null
  rebuild: boolean
  components: string[]
  done: number
}

/** An update of the whole version: a rebuild (`all`) — or, from an API that does not say its scope,
 *  any update (it re-exported every document, and held every one as the old pause did). */
const wholeVersion = (scope: string | null | undefined): boolean => scope === 'all' || scope == null

export function runningUpdate(r: ExportReadiness | undefined): RunningUpdate | null {
  const x = r?.reexport
  if (x && ACTIVE.includes(x.status)) {
    return { jobId: x.jobId, rebuild: wholeVersion(x.scope), components: x.components ?? [], done: x.componentsDone ?? 0 }
  }
  const w = r?.writer
  if (w && (w.kind === 'update' || w.kind === 'rebuild')) {
    return { jobId: w.jobId, rebuild: w.kind === 'rebuild', components: w.components ?? [], done: w.componentsDone ?? 0 }
  }
  return null
}

/** How often R9 is read again: every few seconds while an update or a rebuild writes Word files, so
 *  the progress and the end show; slowly while any other run holds the version — an export or a
 *  resume can last days — so the controls turn on when it ends; not at all otherwise. */
export function readinessPollMs(r: ExportReadiness | undefined): number | false {
  if (!r) return false
  if (runningUpdate(r)) return 2500
  if (r.writer || r.outOfDate?.some((f) => f.updating)) return 15_000
  return false
}

/** A run that holds the version and is not an update (a generation, an export, a CLI run). */
export function holdingRun(r: ExportReadiness | undefined): VersionWriter | null {
  const w = r?.writer
  return w && w.kind !== 'update' && w.kind !== 'rebuild' ? w : null
}

/** An update, a rebuild, an export or a resume writes this component now (the server holds its
 *  corrections: 409 `WORD_FILE_UPDATING`). */
function inUpdateScope(r: ExportReadiness | undefined, group: string | undefined): 'update' | 'rebuild' | null {
  if (!group) return null
  const u = runningUpdate(r)
  if (u && (u.components.includes(group) || (u.rebuild && !u.components.length))) return u.rebuild ? 'rebuild' : 'update'
  const w = r?.writer
  if ((w?.kind === 'export' || w?.kind === 'resume') && w.components?.includes(group)) return 'update'
  return null
}

type DocRef = Pick<Document, 'id' | 'group' | 'status'>

/** Its Word file is being written now: show *Updating…*, not *Update*. An approved document's is
 *  never written (its approved file is kept). */
export function isUpdating(r: ExportReadiness | undefined, doc: DocRef): boolean {
  if (doc.status === 'approved') return false
  if (r?.outOfDate?.some((f) => f.documentId === doc.id && f.updating)) return true
  return inUpdateScope(r, doc.group) !== null
}

/** Corrections to this document wait (the server answers 409 `WORD_FILE_UPDATING`): an update
 *  writes its component now. `rebuild` says the rebuild of every file does. */
export function editHold(r: ExportReadiness | undefined, doc: DocRef): 'update' | 'rebuild' | null {
  if (doc.status === 'approved') return null
  const scope = inUpdateScope(r, doc.group)
  if (scope) return scope
  return r?.outOfDate?.some((f) => f.documentId === doc.id && f.updating) ? 'update' : null
}

/** Progress, per component — never per Word file: "Updating Word files…" and "1 of 2". */
export function progressOf(u: RunningUpdate): { title: string; count: string } {
  const n = u.components.length
  return {
    title: `${u.rebuild ? 'Rebuilding' : 'Updating'} Word files…`,
    count: n > 1 ? `${Math.min(u.done, n)} of ${n}` : '',
  }
}

/* ── Why nothing can start ── */

export interface Wording {
  /** The version's tag ("v1.2.0"). */
  versionTag: string
  /** A component's name from its id. */
  nameOf: (component: string) => string
}

function updateName(u: Pick<RunningUpdate, 'rebuild' | 'components'>, words: Wording): string {
  if (u.rebuild) return `the rebuild of ${words.versionTag}`
  return u.components.length ? `the update of ${compNames(u.components.map(words.nameOf))}` : `the update of ${words.versionTag}`
}

/** What holds the version, by its kind, as the object of "after … ends": an update or a rebuild by
 *  its components (a command-line `reexport` too); a generation, an export or a resume as the
 *  generation (Components → Generate makes documents); any other run as the run. */
function runName(kind: string | null | undefined, components: string[] | null | undefined, words: Wording): string {
  if (kind === 'update' || kind === 'rebuild') return updateName({ rebuild: kind === 'rebuild', components: components ?? [] }, words)
  if (kind === 'other') return `the run on ${words.versionTag}`
  return `the generation of ${words.versionTag}`
}

/** Why an update cannot start now ('' = it can), as one sentence: a generation holds the version
 *  ("Update after the generation of v1.2.0 ends."), or another update runs — one at a time, no
 *  queue ("Update after the update of HVAC Ctrl ends.", or "Brake Controller is already
 *  updating."). `asked`: the components asked for; null = every out-of-date one. */
export function updateBlocked(
  r: ExportReadiness | undefined, asked: string[] | null, words: Wording, rebuild = false,
): string {
  const verb = rebuild ? 'Rebuild' : 'Update'
  const run = holdingRun(r)
  if (run) return `${verb} after ${runName(run.kind, run.components, words)} ends.`
  const u = runningUpdate(r)
  if (!u) return ''
  if (rebuild) return `${verb} after ${updateName(u, words)} ends.`
  const comps = asked ?? componentsOf(outOfDateFiles(r))
  if (!comps.length) return ''
  if (comps.every((c) => u.components.includes(c) || (u.rebuild && !u.components.length))) {
    return `${compNames(comps.map(words.nameOf))} ${comps.length === 1 ? 'is' : 'are'} already updating.`
  }
  return `Update after ${updateName(u, words)} ends.`
}

/** A refusal's sentence: 409 `REEXPORT_RUNNING` (another update, an export or a resume that does not
 *  cover the request: its `kind`, else its `scope`) or `VERSION_BUSY` (a run holds the version: its
 *  `writer`, a command-line `reexport` included). */
export function refusalSentence(
  refusal: { code?: string; kind?: string | null; scope: string | null; components: string[]; writer: VersionWriter | null },
  words: Wording, rebuild = false,
): string {
  const verb = rebuild ? 'Rebuild' : 'Update'
  if (refusal.code === 'VERSION_BUSY') {
    const w = refusal.writer
    return `${verb} after ${runName(w?.kind ?? 'generation', w?.components, words)} ends.`
  }
  const kind = refusal.kind
    ?? (refusal.scope === 'export' ? 'export' : refusal.scope === 'all' ? 'rebuild' : 'update')
  return `${verb} after ${runName(kind, refusal.components, words)} ends.`
}

/** Submit's toast when it could not update the Word file (A5 `word_file.state: out_of_date`):
 *  "Update its Word file after the generation ends." `blocked_by` always carries `kind`, `job_id`,
 *  `components` and `message` (§4.4): `other` — a run the mockup has no words for, or R9 could not
 *  be read — says the server's. */
export function submitBlockedSentence(w: VersionWriter | null, words: Wording): string {
  if (!w || w.kind === 'generation' || w.kind === 'export' || w.kind === 'resume') {
    return 'Update its Word file after the generation ends.'
  }
  if (w.kind === 'other') return w.message?.trim() || `Update its Word file after the run on ${words.versionTag} ends.`
  return `Update its Word file after ${runName(w.kind, w.components, words)} ends.`
}

/* ── A failed update ── */

/** The last update failed — every component of it, or some: the person who started it sees it, with
 *  Try again (their bell says so too); to everyone else its Word files are simply still out of
 *  date. */
export interface FailedUpdate {
  jobId: string
  /** It was to rebuild every Word file and wrote none: Try again rebuilds. */
  rebuild: boolean
  /** The components whose Word files it did not write. */
  components: string[]
  /** Some of its components were written: "Word files updated" for those, this for the rest. */
  partial: boolean
  /** "Update failed — <why>." */
  why: string
}

/** The ONE place a failed update is read from R9's `reexport` (WORD_FILE_UPDATES §4.2): `failed` —
 *  every component failed (`componentsFailed`, else all of `components`) — or `complete` with
 *  `componentsFailed`, the ones that did. Only its starter is told. */
export function visibleFailure(r: ExportReadiness | undefined, meId: string): FailedUpdate | null {
  const x = r?.reexport
  if (!x || !meId || x.startedBy?.userId !== meId) return null
  const failed = x.componentsFailed ?? []
  const why = sentence(x.errorMessage || 'its Word files were not written')
  if (x.status === 'failed') {
    return {
      jobId: x.jobId, rebuild: wholeVersion(x.scope), components: failed.length ? failed : x.components ?? [],
      partial: false, why,
    }
  }
  if (x.status === 'complete' && failed.length) {
    return { jobId: x.jobId, rebuild: false, components: failed, partial: true, why }
  }
  return null
}

/** The components an update that ended wrote: all of them, less the ones that failed. */
export function writtenComponents(x: NonNullable<ExportReadiness['reexport']>): string[] {
  if (x.status !== 'complete') return []
  const failed = new Set(x.componentsFailed ?? [])
  return (x.components ?? []).filter((c) => !failed.has(c))
}

/** The failure shown on this document: its component was in it, and its file is still out of date
 *  (an approved document never is). */
export function failureFor(
  r: ExportReadiness | undefined, meId: string, doc: Pick<Document, 'id' | 'group'>, stale: boolean,
): FailedUpdate | null {
  const f = visibleFailure(r, meId)
  return f && stale && (f.rebuild || (!!doc.group && f.components.includes(doc.group))) ? f : null
}

/** Whether Try again can be sent from here (WORD_FILE_UPDATES D4): an admin's, always; a
 *  developer's only within their reach — the components of the documents they review, plus the
 *  document open. A developer who updated a component from a document they do not review is sent
 *  back to it ("Open Util (SWE.3) to try again"); the server would refuse it anywhere else. */
export type Retry =
  | { kind: 'here' }
  | { kind: 'open'; docId: string; label: string }
  | { kind: 'none' }

export function retryOf(f: FailedUpdate, opts: {
  isAdmin: boolean
  /** The components of the documents this user reviews. */
  reviewed: string[]
  /** The open document's component, when one is open. */
  openGroup?: string
  docs: Pick<Document, 'id' | 'group' | 'name' | 'process' | 'status'>[]
}): Retry {
  if (opts.isAdmin) return { kind: 'here' }
  if (f.rebuild) return { kind: 'none' }
  const reach = new Set([...opts.reviewed, ...(opts.openGroup ? [opts.openGroup] : [])])
  const outside = f.components.filter((c) => !reach.has(c))
  if (!outside.length) return { kind: 'here' }
  const of = opts.docs.filter((d) => d.group === outside[0])
  const d = of.find((x) => x.status !== 'approved' && x.process === 'SWE.3') ?? of.find((x) => x.status !== 'approved') ?? of[0]
  return d ? { kind: 'open', docId: d.id, label: fileLabel({ name: d.name, docType: d.process }) } : { kind: 'none' }
}

/* ── How far this role reaches ── */

/** An update by this role reaches (the server refuses the rest): an admin's, every Word file out
 *  of date; a developer's, the components of the documents they review, plus the document open. */
export function inReach(
  files: OutOfDateFile[], opts: { isAdmin: boolean; reviewed: string[]; openGroup?: string },
): OutOfDateFile[] {
  if (opts.isAdmin) return files
  const comps = new Set([...opts.reviewed, ...(opts.openGroup ? [opts.openGroup] : [])])
  return files.filter((f) => comps.has(f.component))
}

/* ── The Documents page ── */

/** The components of the documents this user reviews in the version. */
function reviewedComponents(docs: Pick<Document, 'id' | 'group'>[], myDocIds: string[]): string[] {
  const mine = new Set(myDocIds)
  return [...new Set(docs.filter((d) => mine.has(d.id)).map((d) => d.group ?? '').filter(Boolean))]
}

/** The Generation banner's Word-files row (documents.html paintGenBanner, row 2): an update in
 *  progress; the update this person started failed; or the version's Word files out of date, with
 *  the one update this role may start — an admin's, all of them; a developer's, the ones they
 *  review. */
export type WordFilesRow =
  | { kind: 'none' }
  /** R9 answered an error: nothing says which Word files are up to date (it fails closed). */
  | { kind: 'unknown' }
  | { kind: 'updating'; title: string; count: string }
  | { kind: 'failed'; failure: FailedUpdate; blocked: string; retry: Retry }
  | {
    kind: 'outOfDate'
    /** Every out-of-date Word file of the version. */
    files: OutOfDateFile[]
    /** The ones this role's update reaches (empty: an admin updates them). */
    mine: OutOfDateFile[]
    /** After the count: why they are out of date (an admin), how many they review (a developer),
     *  or — while nothing can start — when it can. */
    detail: string
    blocked: string
  }

export function wordFilesRow(input: {
  readiness: ExportReadiness | undefined
  /** R9 answered an error. */
  readinessFailed?: boolean
  docs: Pick<Document, 'id' | 'group' | 'name' | 'process' | 'status'>[]
  isAdmin: boolean
  meId: string
  myDocIds: string[]
  words: Wording
}): WordFilesRow {
  const { readiness: r, isAdmin, words } = input
  if (!r) return input.readinessFailed ? { kind: 'unknown' } : { kind: 'none' }
  const u = runningUpdate(r)
  if (u) return { kind: 'updating', ...progressOf(u) }
  const files = outOfDateFiles(r, input.docs)
  const reviewed = reviewedComponents(input.docs, input.myDocIds)
  const f = visibleFailure(r, input.meId)
  // A failure is news while what it was to write is still out of date.
  if (f && files.some((x) => f.rebuild || f.components.includes(x.component))) {
    return {
      kind: 'failed', failure: f, blocked: updateBlocked(r, f.rebuild ? null : f.components, words, f.rebuild),
      retry: retryOf(f, { isAdmin, reviewed, docs: input.docs }),
    }
  }
  if (!files.length) return { kind: 'none' }
  const mine = inReach(files, { isAdmin, reviewed })
  const blocked = mine.length ? updateBlocked(r, isAdmin ? null : componentsOf(mine), words) : ''
  const detail = blocked
    || (isAdmin ? reasonsOf(files) : mine.length ? `${mine.length} you review` : `an admin updates ${files.length === 1 ? 'it' : 'them'}`)
  return { kind: 'outOfDate', files, mine, detail, blocked }
}

/** Download all while Word files are out of date (documents.html renderModal 'dlall'): how many,
 *  what this role may update first (*Corrected files*), and why it cannot now. */
export interface DownloadAllChoice {
  files: OutOfDateFile[]
  /** The ones this role's update reaches. */
  mine: OutOfDateFile[]
  /** "You can update the 2 you review." / "An admin updates them." ('' for an admin). */
  note: string
  blocked: string
}

export function downloadAllChoice(input: {
  readiness: ExportReadiness | undefined
  docs: Pick<Document, 'id' | 'group' | 'name' | 'process' | 'status'>[]
  isAdmin: boolean
  myDocIds: string[]
  words: Wording
}): DownloadAllChoice {
  const { readiness: r, isAdmin } = input
  const files = outOfDateFiles(r, input.docs)
  const mine = inReach(files, { isAdmin, reviewed: reviewedComponents(input.docs, input.myDocIds) })
  const note = isAdmin || mine.length === files.length ? ''
    : mine.length ? `You can update the ${mine.length} you review.` : 'An admin updates them.'
  const blocked = mine.length ? updateBlocked(r, isAdmin ? null : componentsOf(mine), input.words) : ''
  return { files, mine, note, blocked }
}

/* ── The reader's banner ── */

export type ReaderBanner =
  | { kind: 'none' }
  /** R9 answered an error: nothing says whether this Word file is up to date (it fails closed). */
  | { kind: 'unknown' }
  | { kind: 'updating'; title: string; count: string }
  | { kind: 'updated' }
  | { kind: 'failed'; failure: FailedUpdate; blocked: string; retry: Retry }
  | {
    kind: 'outOfDate'
    /** This document's Word files (its component's SWE.3 and SWE.4), when it is out of date. */
    mine: OutOfDateFile[]
    /** Why this document's file is out of date ('' when it is not). */
    why: string
    /** The rest this role's update reaches (not the ones updating now). */
    others: OutOfDateFile[]
    blockedMine: string
    blockedRest: string
    /** Approved documents whose kept file is not changed. */
    kept: OutOfDateFile[]
  }
  | { kind: 'kept'; kept: OutOfDateFile[] }

/** What the reader's banner says for the open document (mockup paintReady): updating its
 *  component, just updated, the update this person started failed, out of date (this file, then
 *  the rest this role reaches), or only "Approved, not changed". */
export function readerBanner(input: {
  readiness: ExportReadiness | undefined
  /** R9 answered an error. */
  readinessFailed?: boolean
  doc: DocRef
  /** Every document of the version (names, the fallback for an older API). */
  docs: Pick<Document, 'id' | 'group' | 'name' | 'process' | 'status'>[]
  isAdmin: boolean
  meId: string
  /** The documents of this version the signed-in user reviews. */
  myDocIds: string[]
  /** The components an update just wrote (for a few seconds after it ends). */
  justUpdated: string[] | null
  words: Wording
}): ReaderBanner {
  const { readiness: r, doc, isAdmin, meId, words } = input
  if (!r) return input.readinessFailed && doc.status !== 'approved' ? { kind: 'unknown' } : { kind: 'none' }
  const files = outOfDateFiles(r, input.docs)
  const stale = doc.status !== 'approved' && files.some((f) => f.documentId === doc.id)

  const u = runningUpdate(r)
  if (isUpdating(r, doc)) {
    return { kind: 'updating', ...progressOf(u ?? { jobId: null, rebuild: false, components: [], done: 0 }) }
  }
  if (input.justUpdated && doc.group && input.justUpdated.includes(doc.group) && !stale && doc.status !== 'approved') {
    return { kind: 'updated' }
  }

  const myIds = new Set(input.myDocIds)
  const reviewed = reviewedComponents(input.docs, input.myDocIds)
  // Only on a document the failed update was to write, still out of date (a partly failed update:
  // its failed components only; the written ones say "Word files updated").
  const f = failureFor(r, meId, doc, stale)
  if (f) {
    return {
      kind: 'failed', failure: f, blocked: updateBlocked(r, f.rebuild ? null : f.components, words, f.rebuild),
      retry: retryOf(f, { isAdmin, reviewed, openGroup: doc.group, docs: input.docs }),
    }
  }

  const mine = stale ? files.filter((x) => x.component === doc.group) : []
  const others = inReach(files, { isAdmin, reviewed })
    .filter((x) => !x.updating && !mine.includes(x) && !(u && (u.components.includes(x.component) || u.rebuild)))
  const kept = (r.approvedKept ?? []).filter((x) => isAdmin || myIds.has(x.documentId))
  if (!mine.length && !others.length) return kept.length ? { kind: 'kept', kept } : { kind: 'none' }
  const own = files.find((x) => x.documentId === doc.id)
  return {
    kind: 'outOfDate',
    mine,
    why: own ? outOfDateWhy(own) : '',
    others,
    blockedMine: mine.length && doc.group ? updateBlocked(r, [doc.group], words) : '',
    blockedRest: others.length ? updateBlocked(r, isAdmin ? null : componentsOf(others), words) : '',
    kept,
  }
}
