import type { ConfigPreview } from '../../types'
import { looksLocal, type Core, type Layer, type Member, type RepoSource } from './helpers'

/* The wizard's draft, kept for this tab only (sessionStorage) so a reload does not start it over:
   the step and what was typed or picked. NEVER the access token, nor the imported file's text — a
   config file can hold a token. The branches and the repository's files are not kept either: they
   are read again from the repository. Cleared when the project is created or the wizard closed. */

const KEY = 'artifex.newProject.draft.v1'

export interface WizardDraft {
  step: number
  /** Steps advanced past (the rail lets you go back to them). */
  done: number[]
  name: string
  /** Git URL or local path: which one `repoUrl` is. */
  repoSource: RepoSource
  repoUrl: string
  branch: string
  /** An access token was in use: the repository is private, and the token must be typed again. */
  tokenUsed: boolean
  cores: Core[]
  layers: Layer[]
  fileAssignments: Record<string, string>
  members: Member[]
  /** An imported config: its name and what it filled in (its settings go into the project). */
  imported: { fileName: string; preview: ConfigPreview } | null
  importKept: string[]
  archEdited: boolean
}

/** The draft of this tab, or null (none, or one this version of the page cannot read). */
export function loadDraft(): WizardDraft | null {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return null
    const d = JSON.parse(raw) as Partial<WizardDraft> | null
    if (!d || typeof d.step !== 'number' || !Array.isArray(d.cores) || !Array.isArray(d.layers)) return null
    return {
      step: d.step,
      done: Array.isArray(d.done) ? d.done.filter((n) => typeof n === 'number') : [],
      name: d.name ?? '',
      // A draft from before the switch: a path is a local path.
      repoSource: d.repoSource === 'local' || d.repoSource === 'url' ? d.repoSource : looksLocal(d.repoUrl ?? '') ? 'local' : 'url',
      repoUrl: d.repoUrl ?? '',
      branch: d.branch ?? '',
      tokenUsed: !!d.tokenUsed,
      cores: d.cores,
      layers: d.layers,
      fileAssignments: d.fileAssignments ?? {},
      members: Array.isArray(d.members) ? d.members : [],
      imported: d.imported?.preview ? { fileName: d.imported.fileName ?? '', preview: d.imported.preview } : null,
      importKept: Array.isArray(d.importKept) ? d.importKept : [],
      archEdited: !!d.archEdited,
    }
  } catch {
    return null
  }
}

/** Keep the draft. Only the fields named here are written, whatever else the caller holds. */
export function saveDraft(d: WizardDraft): void {
  const kept: WizardDraft = {
    step: d.step, done: d.done, name: d.name, repoSource: d.repoSource, repoUrl: d.repoUrl, branch: d.branch, tokenUsed: d.tokenUsed,
    cores: d.cores, layers: d.layers, fileAssignments: d.fileAssignments, members: d.members,
    imported: d.imported ? { fileName: d.imported.fileName, preview: d.imported.preview } : null,
    importKept: d.importKept, archEdited: d.archEdited,
  }
  try {
    sessionStorage.setItem(KEY, JSON.stringify(kept))
  } catch {
    /* private mode or full: the wizard works without a draft */
  }
}

export function clearDraft(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    /* nothing to clear */
  }
}
