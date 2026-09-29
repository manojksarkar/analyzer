import { useRef } from 'react'
import { CodeText, Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { ConfigPreview, ConfigReportLevel } from '../../../types'

const LEVEL: Record<ConfigReportLevel, { icon: string; cls: string }> = {
  filled:  { icon: 'check_circle', cls: 'text-[#00a572]' },
  check:   { icon: 'error',        cls: 'text-[#b45309]' },
  skipped: { icon: 'block',        cls: 'text-outline' },
}

/** Step 1's "start from a config file": pick the file, then what reading it filled in, what
 *  needs the user, and what was left out. */
export function ConfigImport({ fileName, preview, busy, onPick, archChanged, branch, checking }: {
  fileName?: string
  preview?: ConfigPreview
  busy: boolean
  onPick: (file: File) => void
  /** The user changed the imported architecture: a new check no longer replaces it. */
  archChanged: boolean
  branch: string
  /** The paths are being checked against the repository right now. */
  checking: boolean
}) {
  const inputRef = useRef<HTMLInputElement>(null)
  const count = (level: ConfigReportLevel) => preview?.report.filter((r) => r.level === level).length ?? 0

  return (
    <div className="card space-y-3">
      <div className="flex items-center gap-3">
        <div className="card-icon bg-primary-container flex-shrink-0">
          <Icon name="settings_suggest" size={17} className="text-on-primary-container" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-on-surface font-sans text-sm font-semibold">
            Start from a config file <span className="text-on-surface-variant font-normal">(optional)</span>
          </h3>
          <p className="text-on-surface-variant text-caption mt-0.5">
            The config <code className="font-mono">analyzer.py onboard --config</code> reads. It fills every step it can; the access token is never read from it.
          </p>
        </div>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          disabled={busy}
          className="flex items-center gap-1.5 px-4 py-2 border border-outline-variant rounded-lg bg-surface-container-low hover:bg-surface-container transition-colors flex-shrink-0 disabled:opacity-60 font-mono text-caption font-bold tracking-[.06em] uppercase text-on-surface-variant"
        >
          <Icon name={busy ? 'progress_activity' : 'upload_file'} size={15} className={busy ? 'animate-spin' : undefined} />
          {busy ? 'Reading…' : fileName ? 'Import another' : 'Import config'}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".json,.jsonc"
          className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) onPick(f); e.target.value = '' }}
        />
      </div>

      {preview && fileName && (
        <div className="border-t border-outline-variant pt-3">
          <p className="font-mono text-caption text-on-surface-variant mb-2">
            <span className="text-on-surface font-semibold">{fileName}</span>
            {` · ${count('filled')} filled · ${count('check')} to check · ${count('skipped')} not used`}
            {checking
              ? ` · checking the paths against ${branch ? `branch ${branch}` : 'the repository'}…`
              : !preview.repositoryChecked && ' · paths are checked after Test Connection'}
          </p>
          <ul className="space-y-1.5">
            {preview.report.map((item, i) => (
              <li key={i} className="flex items-start gap-2 text-xs text-on-surface">
                <Icon name={LEVEL[item.level].icon} size={14} fill className={cn('flex-shrink-0 mt-px', LEVEL[item.level].cls)} />
                <span className="leading-[1.45]"><CodeText text={item.text} /></span>
              </li>
            ))}
          </ul>
          {archChanged && (
            <p className="mt-2 flex items-start gap-2 text-xs text-on-surface-variant">
              <Icon name="info" size={14} className="flex-shrink-0 mt-px text-secondary" />
              <span className="leading-[1.45]">
                You changed the architecture after importing, so a new check leaves it as it is.
                Step 3 checks every path against {branch ? <CodeText text={`branch \`${branch}\``} /> : 'the branch'}, and the project is created only when all of them are there.
              </span>
            </p>
          )}
        </div>
      )}
    </div>
  )
}
