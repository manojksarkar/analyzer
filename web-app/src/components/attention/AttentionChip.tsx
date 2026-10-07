import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Drawer, Icon, toast } from '../ui'
import { useProject } from '../../hooks/useProjects'
import { useAttention } from '../../hooks/useAttention'
import { attentionChip, type AttentionItem } from '../../lib/attention'
import { cn } from '../../lib/cn'
import { useRunModal } from '../../store/runModal'
import { FailedRunBanner, RunWarningsBanner } from './RunBanners'
import { OtherRuns } from './OtherRuns'

/* Needs attention: one chip beside the version, on every project page, instead of the banners
   that stacked on the Overview (at the office: a failed run, one box per other run, the warnings,
   the generation). Its drawer holds each of them, with the same buttons. The version's own
   generation keeps its row on the Overview -- Generate, Stop, Resume, Word files -- and is listed
   here with a way there. A toast says when something new needs attention. */

export function AttentionChip() {
  const { projectId = '' } = useParams<{ projectId: string }>()
  const { data: project } = useProject(projectId)
  const isAdmin = project?.userRole === 'admin'
  const { items, exceptVersionIds } = useAttention(projectId)
  const chip = attentionChip(items)
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const openRun = useRunModal((s) => s.openRun)
  useAttentionToasts(items, () => setOpen(true))

  if (!chip) return null
  const toOverview = () => { setOpen(false); navigate(`/projects/${projectId}/overview`) }
  return (
    <>
      <span className="text-outline-variant select-none" aria-hidden>·</span>
      <button type="button" onClick={() => setOpen(true)} title="Needs attention: what failed, stopped, is at work or warned"
        className={cn('inline-flex items-center gap-1.5 px-2.5 py-[3px] rounded-full border font-mono text-caption font-semibold whitespace-nowrap transition-colors',
          chip.tone === 'warn'
            ? 'bg-state-warn-bg border-amber text-state-warn hover:brightness-95'
            : 'bg-surface-container border-state-busy-line text-secondary hover:bg-surface-container-high')}>
        <Icon name={chip.tone === 'warn' ? 'warning' : 'autorenew'} size={13} fill={chip.tone === 'warn'}
          className={chip.tone === 'busy' ? 'animate-spin' : undefined} />
        {chip.label}
      </button>
      <Drawer open={open} onClose={() => setOpen(false)} title="Needs attention"
        description={`${chip.count} thing${chip.count === 1 ? '' : 's'}: runs that failed, stopped or are at work, and what a run warned about.`}>
        <div className="px-6 pt-5">
        {items.map((it) => {
          switch (it.kind) {
            case 'failed':
              return <FailedRunBanner key={`failed-${it.job.id}`} projectId={projectId} job={it.job} isAdmin={isAdmin}
                onRerun={() => { openRun(); toOverview() }} />
            case 'generating':
            case 'stopped':
              return (
                <div key={`gen-${it.version.id}`} role="status"
                  className={cn('mb-6 flex items-center gap-3 px-4 py-3 rounded-xl border',
                    it.kind === 'stopped' ? 'bg-warn-bg border-state-warn-line' : 'bg-surface-container-lowest border-outline-variant')}>
                  <Icon name={it.kind === 'stopped' ? 'pause_circle' : 'autorenew'} size={18}
                    className={cn('flex-shrink-0', it.kind === 'stopped' ? 'text-caution' : 'text-secondary animate-spin')} />
                  <p className="flex-1 min-w-0 text-body text-on-surface">
                    <b className="font-semibold">{it.version.tag}</b> · {it.text}
                  </p>
                  <button type="button" onClick={toOverview} className="flex-shrink-0 text-caption font-semibold text-secondary hover:underline">
                    {it.kind === 'stopped' ? 'Resume on the Overview' : 'Open the Overview'}
                  </button>
                </div>
              )
            case 'runs':
              return <OtherRuns key="runs" projectId={projectId} exceptVersionIds={exceptVersionIds} />
            case 'warnings':
              return <RunWarningsBanner key={`warn-${it.version.id}`} version={it.version} />
          }
        })}
        </div>
      </Drawer>
    </>
  )
}

/** A toast when something new needs attention: a failed analysis (once per browser tab) and a
 *  version's warnings (once per browser). Remembered in storage, which may be unavailable. */
function useAttentionToasts(items: AttentionItem[], show: () => void) {
  const showRef = useRef(show)
  useEffect(() => { showRef.current = show })
  const failed = items.find((i): i is Extract<AttentionItem, { kind: 'failed' }> => i.kind === 'failed')
  const warned = items.find((i): i is Extract<AttentionItem, { kind: 'warnings' }> => i.kind === 'warnings')
  const failedId = failed?.job.id
  const failedTag = failed?.job.versionTag
  const warnedId = warned?.version.id
  const warnedTag = warned?.version.tag
  const warnedCount = warned?.version.warnings.length ?? 0

  useEffect(() => {
    if (!failedId || !firstTime(sessionStorageOrNull(), `attention.failed.${failedId}`)) return
    toast.info(`Analysis failed${failedTag ? ` — ${failedTag}` : ''}`, 'Why it failed is under Needs attention.',
      { label: 'Show', onClick: () => showRef.current() })
  }, [failedId, failedTag])

  useEffect(() => {
    if (!warnedId || !firstTime(localStorageOrNull(), `attention.warnings.${warnedId}`)) return
    toast.info(`The run that made ${warnedTag} reported ${warnedCount} warning${warnedCount === 1 ? '' : 's'}`,
      'Its documents lack what they name.', { label: 'Show', onClick: () => showRef.current() })
  }, [warnedId, warnedTag, warnedCount])
}

function firstTime(store: Storage | null, key: string): boolean {
  if (!store) return true
  try {
    if (store.getItem(key)) return false
    store.setItem(key, '1')
  } catch {
    // storage refused (private window, quota): say it each time rather than never
  }
  return true
}
const sessionStorageOrNull = (): Storage | null => { try { return window.sessionStorage } catch { return null } }
const localStorageOrNull = (): Storage | null => { try { return window.localStorage } catch { return null } }
