import type { ReactNode } from 'react'
import { Link as RouterLink } from 'react-router-dom'
import { Icon } from '../../../components/ui'
import { WordFileMenu } from '../../../components/wordfiles/WordFileMenu'
import { cn } from '../../../lib/cn'
import { fileLabel, plural, type ReaderBanner, type UpdateAsk } from '../../../lib/wordFiles'

/* The open document's Word file (documents.html paintReady; WORD_FILE_UPDATES §3, W2): out of
   date and why, with Update; one line for the rest this role's update reaches — an admin's, the
   version's (Update all); a developer's, the ones they review (Update them); "Approved, not
   changed"; while an update writes it, its progress; then "Word files updated · Download"; a
   failed update, to its starter, with Try again. An admin's ⋯ adds Rebuild all. Every control
   that cannot start now is off, its reason in its tooltip and on one line. The state is worked
   out in lib/wordFiles.ts (readerBanner). */

const TONE = {
  warn: { box: 'bg-[#fffbeb] border-[#fcd34d]', text: 'text-[#92400e]', icon: 'text-[#b45309]' },
  info: { box: 'bg-[#fffbeb] border-[#fcd34d]', text: 'text-[#92400e]', icon: 'text-secondary' },
  ok: { box: 'bg-[#f0fdf9] border-[#86efac]', text: 'text-[#065f46]', icon: 'text-[#00a572]' },
  bad: { box: 'bg-[#fff1f0] border-[#f5a3a3]', text: 'text-[#93000a]', icon: 'text-error' },
} as const

export function WordFileBanner({
  projectId, state, isAdmin, rebuildBlocked, failedRenders, onAsk, onDownload,
}: {
  projectId: string
  state: ReaderBanner
  isAdmin: boolean
  /** Why Rebuild all cannot start now ('' = it can). */
  rebuildBlocked: string
  /** Pictures that could not be redrawn (R9 `failedRenders`): said when nothing else is. */
  failedRenders: number
  /** Ask for an update: the confirm dialog says what it writes. */
  onAsk: (ask: UpdateAsk) => void
  /** Download the open document's Word file. */
  onDownload: () => void
}) {
  const more = isAdmin ? (
    <WordFileMenu
      label="More"
      trigger={(
        <button type="button" aria-label="More" title="More" className="p-1 rounded-lg text-[#92400e] hover:bg-[#fde68a55] flex-shrink-0">
          <Icon name="more_vert" size={18} />
        </button>
      )}
      items={[{
        icon: 'autorenew',
        label: 'Rebuild all Word files…',
        sub: rebuildBlocked || undefined,
        disabled: !!rebuildBlocked,
        onSelect: () => onAsk({ components: null, rebuild: true }),
      }]}
    />
  ) : null

  switch (state.kind) {
    case 'updating':
      return (
        <Banner tone="warn" icon="autorenew" spin>
          <b>{state.title}</b>{state.count ? ` ${state.count}` : ''}
        </Banner>
      )
    case 'updated':
      return (
        <Banner tone="ok" icon="check_circle">
          <b>Word files updated.</b> <Link onClick={onDownload}>Download</Link>
        </Banner>
      )
    case 'unknown':
      // R9 failed closed: never "up to date" from an error.
      return (
        <Banner tone="bad" icon="error">
          <b>Can’t tell if this Word file is up to date.</b>
        </Banner>
      )
    case 'failed': {
      const f = state.failure
      const retry = state.retry
      return (
        <Banner
          tone="bad"
          icon="error"
          lines={retry.kind === 'open' || (retry.kind === 'here' && state.blocked) ? (
            <>
              {retry.kind === 'open' && (
                // A developer's update from a document they do not review reaches it only from there.
                <span className="block text-on-surface-variant">
                  Open <RouterLink to={`/projects/${projectId}/documents/${retry.docId}`} className="text-secondary font-semibold hover:underline">{retry.label}</RouterLink> to try again.
                </span>
              )}
              {retry.kind === 'here' && state.blocked && <Note>{state.blocked}</Note>}
            </>
          ) : null}
          action={(
            <>
              {retry.kind === 'here' && (
                <UpdateButton label="Try again" blocked={state.blocked}
                  onClick={() => onAsk({ components: f.rebuild ? null : f.components, rebuild: f.rebuild })} />
              )}
              {more}
            </>
          )}
        >
          <b>Update failed</b> — {f.why}
        </Banner>
      )
    }
    case 'kept':
      return (
        <Banner tone="info" icon="info" action={more}>
          <b>Approved, not changed</b> · {state.kept.map(fileLabel).join(', ')}
        </Banner>
      )
    case 'outOfDate': {
      const { mine, others, kept, blockedMine, blockedRest } = state
      const n = others.length
      const comps = [...new Set(others.map((o) => o.component))]
      const rest = !n || blockedRest ? null : (
        <> · <Link onClick={() => onAsk({ components: isAdmin ? null : comps })}>
          {isAdmin ? 'Update all' : n === 1 ? 'Update it' : 'Update them'}
        </Link></>
      )
      const blocked = blockedMine || blockedRest
      const lines = (
        <>
          {mine.length > 0 && n > 0 && (
            <span className="block">{isAdmin ? `${n} more ${n === 1 ? 'is' : 'are'} out of date` : `${n} more you review`}{rest}</span>
          )}
          {blocked && <Note>{blocked}</Note>}
          {kept.length > 0 && <span className="block">Approved, not changed: {kept.map(fileLabel).join(', ')}</span>}
        </>
      )
      if (mine.length) {
        return (
          <Banner
            tone="warn"
            icon="warning"
            lines={lines}
            action={(
              <>
                <UpdateButton label="Update" blocked={blockedMine} title={`Updates ${mine.map(fileLabel).join(' and ')}`}
                  onClick={() => onAsk({ components: [mine[0].component] })} />
                {more}
              </>
            )}
          >
            <b>This Word file is out of date</b> · {state.why}
          </Banner>
        )
      }
      return (
        <Banner tone="info" icon="info" lines={lines} action={more}>
          <b>{plural(n, 'Word file')} {isAdmin ? '' : 'you review '}{n === 1 ? 'is' : 'are'} out of date</b>{rest}
        </Banner>
      )
    }
    default:
      return failedRenders ? (
        <Banner tone="warn" icon="image_not_supported">
          {plural(failedRenders, 'flowchart picture')} could not be redrawn for the Word file. Its text is up to date.
        </Banner>
      ) : null
  }
}

function Banner({ tone, icon, spin, lines, action, children }: {
  tone: keyof typeof TONE
  icon: string
  spin?: boolean
  /** Lines under the first: the rest, why nothing can start, the approved files kept. */
  lines?: ReactNode
  action?: ReactNode
  children: ReactNode
}) {
  const t = TONE[tone]
  return (
    <div role="status" aria-label="Word file" className={cn('mb-4 flex items-center gap-2.5 px-3.5 py-2.5 rounded-xl border', t.box)}>
      <Icon name={icon} size={18} className={cn('flex-shrink-0', t.icon, spin && 'animate-spin')} />
      <div className="flex-1 min-w-0">
        <p className={cn('text-xs leading-[1.45]', t.text)}>{children}</p>
        {lines && <div className="mt-0.5 text-xs leading-[17px] text-[#92400e]">{lines}</div>}
      </div>
      {action}
    </div>
  )
}

function Note({ children }: { children: ReactNode }) {
  return <span className="block text-on-surface-variant">{children}</span>
}

function Link({ onClick, children }: { onClick: () => void; children: ReactNode }) {
  return (
    <button type="button" onClick={onClick} className="text-secondary font-semibold hover:underline">
      {children}
    </button>
  )
}

/** The banner's one button: a plain verb, off with its reason in the tooltip while nothing can start. */
function UpdateButton({ label, blocked, title, onClick }: {
  label: string; blocked: string; title?: string; onClick: () => void
}) {
  return (
    // The tooltip sits on a wrapper: a disabled button gets no pointer events.
    <span title={blocked || title} className="flex-shrink-0">
      <button
        type="button"
        disabled={!!blocked}
        onClick={onClick}
        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-[6px] bg-secondary text-white font-mono text-label font-semibold tracking-[0.03em] whitespace-nowrap hover:bg-secondary-container disabled:opacity-45 disabled:cursor-not-allowed disabled:hover:bg-secondary"
      >
        <Icon name="sync" size={13} />{label}
      </button>
    </span>
  )
}
