import type { Selection } from '../store/ui'
import type { Version } from '../types'

/**
 * The Subbar's pick as it stands: a pick naming a version that is no longer there — a cancelled
 * run's draft, a deleted version — is no pick, so the default version shows. Kept, it resolved to
 * no version at all: the pages read every version's documents, and the Subbar's chip read
 * "main @ ". Until the versions are loaded a pick is taken as it is.
 */
export function liveSelection(
  selection: Selection | undefined, versions: Version[] | undefined,
): Selection | undefined {
  if (selection?.type === 'version' && versions && !versions.some((v) => v.id === selection.id)) return undefined
  return selection
}
