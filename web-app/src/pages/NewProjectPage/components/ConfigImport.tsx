import { useRef, useState } from 'react'
import { CodeText, Icon, Modal } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { ConfigPreview, ConfigReportItem, ConfigReportLevel, ConfigReportTopic } from '../../../types'

const LEVEL: Record<ConfigReportLevel, { icon: string; cls: string; title: string }> = {
  check:   { icon: 'error',        cls: 'text-[#b45309]', title: 'Needs your attention' },
  filled:  { icon: 'check_circle', cls: 'text-[#00a572]', title: 'Filled in' },
  skipped: { icon: 'block',        cls: 'text-outline',   title: 'Not used' },
}

/** Where the wizard deals with what a report item is about. */
const WHERE: Record<ConfigReportTopic, string> = {
  project: 'Step 1', repository: 'Step 1', files: 'Step 2 · Cores', architecture: 'Step 3 · Architecture',
  settings: 'Step 5 · Review', other: '',
}

function ReportList({ items }: { items: ConfigReportItem[] }) {
  return (
    <ul className="space-y-2">
      {items.map((item, i) => (
        <li key={i} className="flex items-start gap-2 text-xs text-on-surface">
          <Icon name={LEVEL[item.level].icon} size={14} fill className={cn('flex-shrink-0 mt-px', LEVEL[item.level].cls)} />
          <span className="flex-1 leading-[1.45]"><CodeText text={item.text} /></span>
          {WHERE[item.topic] && (
            <span className="flex-shrink-0 font-mono text-micro text-outline whitespace-nowrap mt-px">{WHERE[item.topic]}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

/** Step 1's optional "start from a config file": one compact row. After an import it says what
 *  was filled and how much needs the user - and where - with the full report in a popup. */
export function ConfigImport({ fileName, preview, busy, onPick, archChanged, branch, checking, kept }: {
  fileName?: string
  preview?: ConfigPreview
  busy: boolean
  onPick: (file: File) => void
  /** The user changed the imported architecture: a new check no longer replaces it. */
  archChanged: boolean
  branch: string
  /** The paths are being checked against the repository right now. */
  checking: boolean
  /** What the config also named but the wizard kept the user's own value for. */
  kept: string[]
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const items = preview?.report ?? []
  const of = (level: ConfigReportLevel) => items.filter((r) => r.level === level)
  const attention = of('check')
  // "2 in Cores, 4 in Architecture": where the items needing the user will be dealt with.
  const whereCounts = Object.entries(attention.reduce<Record<string, number>>((acc, it) => {
    const w = (WHERE[it.topic] || 'Other').split(' · ').pop() as string
    acc[w] = (acc[w] ?? 0) + 1
    return acc
  }, {})).map(([w, n]) => `${n} in ${w}`).join(', ')

  const pick = (
    <input ref={inputRef} type="file" accept=".json,.jsonc" className="hidden"
      onChange={(e) => { const f = e.target.files?.[0]; if (f) onPick(f); e.target.value = '' }} />
  )
  const button = (label: string, icon: string, onClick: () => void, primary = false) => (
    <button type="button" onClick={onClick} disabled={busy}
      className={cn('flex items-center gap-1.5 px-3 py-1.5 border rounded-lg transition-colors flex-shrink-0 disabled:opacity-60 font-mono text-caption font-semibold',
        primary ? 'border-secondary text-secondary hover:bg-surface-container-low' : 'border-outline-variant text-on-surface-variant hover:bg-surface-container-low')}>
      <Icon name={icon} size={14} className={cn(busy && icon === 'progress_activity' && 'animate-spin')} />{label}
    </button>
  )

  if (!preview || !fileName) {
    return (
      <div className="flex items-center gap-3 px-4 py-3 border border-dashed border-outline-variant rounded-xl bg-white">
        <Icon name="settings_suggest" size={18} className="text-secondary flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-on-surface">Have a config file? <span className="text-on-surface-variant">Optional</span></p>
          <p className="text-caption text-on-surface-variant mt-0.5">
            Fills the cores and the architecture from the config <code className="font-mono">analyzer.py onboard --config</code> reads. The access token is never read from it.
          </p>
        </div>
        {button(busy ? 'Reading…' : 'Import config', busy ? 'progress_activity' : 'upload_file', () => inputRef.current?.click(), true)}
        {pick}
      </div>
    )
  }

  return (
    <div className="px-4 py-3 border border-outline-variant rounded-xl bg-white">
      <div className="flex items-center gap-3">
        <Icon name="description" size={18} className="text-secondary flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="font-mono text-xs font-semibold text-on-surface truncate">{fileName}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-caption">
            <span className="flex items-center gap-1 text-[#00a572]"><Icon name="check_circle" size={13} fill />{of('filled').length} filled</span>
            {attention.length > 0 && (
              <span className="flex items-center gap-1 text-[#b45309]"><Icon name="error" size={13} fill />
                {attention.length} need{attention.length === 1 ? 's' : ''} attention{whereCounts && ` (${whereCounts})`}
              </span>
            )}
            {of('skipped').length > 0 && <span className="text-outline">{of('skipped').length} not used</span>}
            {checking
              ? <span className="flex items-center gap-1 text-on-surface-variant"><Icon name="progress_activity" size={13} className="animate-spin" />checking paths on {branch || 'the repository'}…</span>
              : !preview.repositoryChecked && <span className="text-on-surface-variant">paths are checked after Test Connection</span>}
          </p>
        </div>
        {button('View details', 'list_alt', () => setOpen(true))}
        {button(busy ? 'Reading…' : 'Replace', busy ? 'progress_activity' : 'swap_horiz', () => inputRef.current?.click())}
        {pick}
      </div>
      {kept.length > 0 && (
        <p className="mt-2 ml-[30px] text-caption text-on-surface-variant">Kept your {kept.join(' and ')}; the config&apos;s were not used.</p>
      )}

      <Modal open={open} onClose={() => setOpen(false)} title={`What ${fileName} filled in`}
        description="Items that need your attention are dealt with in the step named beside them."
        className="max-w-2xl">
        <div className="max-h-[60vh] overflow-y-auto space-y-5 pr-1">
          {(['check', 'filled', 'skipped'] as ConfigReportLevel[]).map((level) => of(level).length > 0 && (
            <section key={level}>
              <p className="mb-2 font-mono text-label font-bold uppercase tracking-[.08em] text-on-surface-variant">
                {LEVEL[level].title} · {of(level).length}
              </p>
              <ReportList items={of(level)} />
            </section>
          ))}
          {archChanged && (
            <p className="flex items-start gap-2 text-xs text-on-surface-variant">
              <Icon name="info" size={14} className="flex-shrink-0 mt-px text-secondary" />
              <span className="leading-[1.45]">
                You changed the architecture after importing, so a new check leaves it as it is.
                Step 3 checks every path against {branch ? <CodeText text={`branch \`${branch}\``} /> : 'the branch'}, and the project is created only when all of them are there.
              </span>
            </p>
          )}
        </div>
      </Modal>
    </div>
  )
}
