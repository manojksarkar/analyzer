import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Button, Icon, toast } from '../ui'
import { cn } from '../../lib/cn'
import {
  componentsOf, outOfDateFiles, plural, updateBlocked, type UpdateAsk, type Wording, type WordFilesRow as RowState,
} from '../../lib/wordFiles'
import type { Document, ExportReadiness } from '../../types'
import { UpdateWordFilesDialog } from './UpdateWordFilesDialog'

/* The Generation banner's second row (documents.html paintGenBanner, WORD_FILE_UPDATES W5): an
   update in progress ("Updating Word files… 1 of 2"); the update this person started failed, with
   Try again; or "N Word files are out of date · reasons" with the one update this role may start —
   an admin's Update all, a developer's Update them (the documents they review). Every button that
   starts an update asks first; while nothing can start, it is off and says why. */

export function WordFilesRow({
  projectId, versionId, state, readiness, docs, isAdmin, words,
}: {
  projectId: string
  versionId: string
  state: RowState
  readiness: ExportReadiness | undefined
  docs: Pick<Document, 'id' | 'group' | 'name' | 'process' | 'status'>[]
  isAdmin: boolean
  words: Wording
}) {
  const [ask, setAsk] = useState<UpdateAsk | null>(null)
  if (state.kind === 'none') return null

  function askUpdate(a: UpdateAsk) {
    const why = updateBlocked(readiness, a.rebuild ? null : a.components, words, !!a.rebuild)
    if (why) toast.info(why)
    else setAsk(a)
  }

  let icon = 'warning'
  let tone = 'text-warn'
  let text: React.ReactNode
  let action: React.ReactNode = null
  if (state.kind === 'unknown') {
    // R9 failed closed: never "up to date" from an error.
    icon = 'error'
    tone = 'text-error'
    text = <b className="font-semibold text-on-surface">Can’t tell which Word files are out of date.</b>
  } else if (state.kind === 'updating') {
    icon = 'autorenew'
    tone = 'text-secondary animate-spin'
    text = <><b className="font-semibold text-on-surface">{state.title}</b>{state.count ? ` ${state.count}` : ''}</>
  } else if (state.kind === 'failed') {
    const f = state.failure
    const retry = state.retry
    icon = 'error'
    tone = 'text-warn'
    text = (
      <>
        <b className="font-semibold text-on-surface">Update failed</b> — {f.why}
        {retry.kind === 'open' && (
          // A developer's update from a document they do not review reaches it only from there.
          <span className="block">
            Open <Link to={`/projects/${projectId}/documents/${retry.docId}`} className="text-secondary font-semibold hover:underline">{retry.label}</Link> to try again.
          </span>
        )}
      </>
    )
    if (retry.kind === 'here') {
      action = <RowButton label="Try again" blocked={state.blocked}
        onClick={() => askUpdate({ components: f.rebuild ? null : f.components, rebuild: f.rebuild })} />
    }
  } else {
    const n = state.files.length
    text = <><b className="font-semibold text-on-surface">{plural(n, 'Word file')} {n === 1 ? 'is' : 'are'} out of date</b> · {state.detail}</>
    if (state.mine.length) {
      action = <RowButton label={isAdmin ? 'Update all' : 'Update them'} blocked={state.blocked}
        onClick={() => askUpdate({ components: isAdmin ? null : componentsOf(state.mine) })} />
    }
  }

  return (
    <>
      <div role="status" aria-label="Word files" className="flex items-center flex-wrap gap-x-3.5 gap-y-2 px-4 py-2.5">
        <Icon name={icon} size={18} className={cn('flex-shrink-0', tone)} />
        <p className="flex-[1_1_220px] min-w-0 text-body text-on-surface-variant">{text}</p>
        {action}
      </div>
      {ask && (
        <UpdateWordFilesDialog
          projectId={projectId}
          versionId={versionId}
          ask={ask}
          files={outOfDateFiles(readiness, docs)}
          rebuildCount={docs.filter((d) => d.status !== 'approved').length}
          words={words}
          onClose={() => setAsk(null)}
        />
      )}
    </>
  )
}

/** One plain verb, off with its reason in the tooltip while nothing can start. */
function RowButton({ label, blocked, onClick }: { label: string; blocked: string; onClick: () => void }) {
  return (
    // The tooltip sits on a wrapper: a disabled button gets no pointer events.
    <span title={blocked || undefined} className="flex-shrink-0">
      <Button variant="outline" size="sm" disabled={!!blocked} onClick={onClick}
        className="h-auto py-1.5 rounded-[6px] bg-surface-container-lowest whitespace-nowrap">
        {label}
      </Button>
    </span>
  )
}
