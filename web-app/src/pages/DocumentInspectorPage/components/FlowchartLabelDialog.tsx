import { useState } from 'react'
import { Button, Icon, Modal, Text } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import { formatShortDate } from '../../../lib/format'
import { useFlowchartLabels, useSaveFlowchartLabels, useUndoSlot } from '../../../hooks/useReview'
import type { FlowchartEntry, Slot } from '../../../types'
import { MAX_TEXT } from '../editContext'

/* One flowchart's box labels, corrected together (R7 reads them, R8 saves the changed ones all
   or nothing). The chart's shape and arrows come from the code and stay as they are; the server
   redraws the picture on save, and the SWE.4 test steps built from the labels follow. */

function nodeNumber(s: Slot): number {
  const n = Number((s.nodeId ?? '').replace(/\D+/g, ''))
  return Number.isFinite(n) ? n : 0
}

export function FlowchartLabelDialog({
  chart, projectId, versionId, locked, userName, onClose,
}: {
  chart: FlowchartEntry
  projectId: string
  versionId: string
  locked: boolean
  userName: (id: string | null) => string
  onClose: () => void
}) {
  const { data, isLoading, isError, error } = useFlowchartLabels(projectId, versionId, chart.flowchartId)
  const save = useSaveFlowchartLabels(projectId, versionId)
  const undo = useUndoSlot(projectId, versionId)
  // Only what the reviewer typed, by node id; everything else reads from R7.
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [focused, setFocused] = useState<string | null>(null)

  const labels = [...(data?.labels ?? [])].sort((a, b) => nodeNumber(a) - nodeNumber(b))
  const valueOf = (s: Slot) => draft[s.nodeId ?? ''] ?? s.text
  const changed = labels.filter((s) => valueOf(s).trim() !== s.text.trim())
  const empty = labels.some((s) => !valueOf(s).trim())
  const tooLong = labels.some((s) => valueOf(s).length > MAX_TEXT)

  function close() {
    if (changed.length && !window.confirm(`Discard ${changed.length} changed label${changed.length === 1 ? '' : 's'}?`)) return
    onClose()
  }

  function submit() {
    if (!chart.flowchartId || !changed.length || empty || tooLong) return
    const body: Record<string, string> = {}
    for (const s of changed) if (s.nodeId) body[s.nodeId] = valueOf(s).replace(/\s+/g, ' ').trim()
    save.mutate({ flowchartId: chart.flowchartId, labels: body }, { onSuccess: () => onClose() })
  }

  return (
    <Modal open onClose={close} title={`Edit flowchart — ${chart.label}`} className="max-w-5xl w-[94vw]">
      <div className="-mx-6 border-y border-outline-variant grid grid-cols-1 md:grid-cols-[1fr_360px] max-h-[70vh] min-h-[320px]">
        <div className="overflow-auto bg-surface p-4 border-b md:border-b-0 md:border-r border-outline-variant flex justify-center items-start">
          {chart.imageUrl
            ? <img src={chart.imageUrl} alt={`Flowchart of ${chart.label}`} className="block max-w-full h-auto" />
            : <Text variant="caption" className="font-mono">No picture for this run.</Text>}
        </div>
        <div className="overflow-y-auto px-4 py-3">
          <Text as="p" variant="caption" className="mb-2">
            Box labels, in the order the code runs them. The shape and the arrows come from the code and stay as they are.
          </Text>
          {isLoading && <Text as="p" variant="caption" className="font-mono">Loading labels…</Text>}
          {isError && (
            <p className="flex items-center gap-1 text-caption text-error">
              <Icon name="error" size={14} />{error instanceof Error ? error.message : 'Could not read the labels.'}
            </p>
          )}
          {data && !data.graphAvailable && (
            <Text as="p" variant="caption">{data.note ?? 'This flowchart has no stored graph to edit.'}</Text>
          )}
          {labels.map((s, i) => {
            const isChanged = valueOf(s).trim() !== s.text.trim()
            return (
              <div key={s.key} className="flex gap-2.5 py-2 border-b border-surface-container last:border-0">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-primary text-white font-mono text-label leading-5 text-center">{i + 1}</span>
                <div className="flex-1 min-w-0">
                  <textarea
                    value={valueOf(s)}
                    rows={2}
                    readOnly={locked}
                    aria-label={`Label of box ${i + 1}`}
                    onFocus={() => setFocused(s.key)}
                    onBlur={() => setFocused(null)}
                    onChange={(e) => setDraft((d) => ({ ...d, [s.nodeId ?? '']: e.target.value }))}
                    className={cn(
                      'w-full resize-y rounded-lg border px-2 py-1.5 text-xs text-on-surface outline-none',
                      isChanged ? 'border-secondary bg-surface-container-low' : 'border-outline-variant bg-white',
                      focused === s.key && 'ring-2 ring-secondary',
                    )}
                  />
                  <p className="font-mono text-label text-outline mt-0.5 flex flex-wrap gap-x-1.5">
                    <span>{s.nodeId}</span>
                    <span>·</span>
                    {s.isOverridden ? (
                      <>
                        <span>corrected{s.updatedBy ? ` by ${userName(s.updatedBy)}` : ''}{s.updatedAt ? ` · ${formatShortDate(s.updatedAt)}` : ''}</span>
                        {s.canUndo && !locked && (
                          <>· <button type="button" onClick={() => undo.mutate(s)} className="text-secondary hover:underline">Undo</button></>
                        )}
                      </>
                    ) : <span>written by the LLM</span>}
                    {isChanged && <span className="text-secondary font-semibold">· changed</span>}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
      <div className="flex items-center justify-between gap-4 pt-4">
        <Text as="p" variant="caption" className={empty || tooLong ? 'text-error font-semibold' : ''}>
          {empty ? 'A label can’t be empty.'
            : tooLong ? `Keep each label under ${MAX_TEXT.toLocaleString()} characters.`
              : 'Saves the changed labels together. The picture is redrawn, and the SWE.4 test steps use the new wording.'}
        </Text>
        <div className="flex items-center gap-2 flex-shrink-0">
          <Button variant="outline" size="sm" onClick={close}>Cancel</Button>
          <Button size="sm" loading={save.isPending} disabled={!changed.length || empty || tooLong || locked} onClick={submit}>
            {changed.length ? `Save ${changed.length} label${changed.length === 1 ? '' : 's'}` : 'Save'}
          </Button>
        </div>
      </div>
    </Modal>
  )
}
