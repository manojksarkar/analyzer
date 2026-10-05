import type { VersionRunInfo } from '../types'

/* How a version was made, in one line for its card: "Web run · 7 components · SWE.3 + SWE.4",
   "Command line · layer Layer1 · model only". */

const SCOPE_WORDS: Record<string, [string, string]> = {
  layer: ['layer', 'layers'],
  group: ['group', 'groups'],
  component: ['component', 'components'],
}

const DOC_TYPE: Record<string, string> = { swe3: 'SWE.3', swe4: 'SWE.4', all: 'SWE.3 + SWE.4' }

function scopeWords(scope: VersionRunInfo['scope']): string | null {
  if (!scope) return null
  const words = SCOPE_WORDS[scope.type]
  if (!words || !scope.names.length) return 'whole project'
  const n = scope.names.length
  if (n === 1) return `${words[0]} ${scope.names[0]}`
  // A few by name; a long list by count.
  return n <= 2 ? `${words[1]} ${scope.names.join(', ')}` : `${n} ${words[1]}`
}

/** One line, or null when the API said nothing about the run. */
export function describeVersionRun(run: VersionRunInfo | null | undefined): string | null {
  if (!run) return null
  const parts = [
    run.madeBy === 'web' ? 'Web run' : run.madeBy === 'cli' ? 'Command line' : null,
    scopeWords(run.scope),
    run.modelOnly ? 'model only' : run.docType ? DOC_TYPE[run.docType] : null,
  ].filter((p): p is string => !!p)
  return parts.length ? parts.join(' · ') : null
}
