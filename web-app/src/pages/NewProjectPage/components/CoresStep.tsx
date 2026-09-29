import { useRef, useState, type ReactNode } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { CoreInputs, UploadedFile } from '../../../types'
import { CORE_FILES, typedDefines, type Core, type CoreFile, type Layer } from '../helpers'

/** A file an imported config names that the repository does not have, per core input. */
type Wanted = CoreInputs<string | null> | undefined

/** One input's control: an upload button, or - once there is a file - a pill with its name,
 *  size, Replace and Remove. A file an imported config names but the repository lacks asks for
 *  itself by name. */
function FileControl({ slot, file, want, icon, busy, onPick, onClear }: {
  slot: CoreFile
  file: UploadedFile | null
  want?: string | null
  icon: string
  busy: boolean
  onPick: (f: File) => void
  onClear: () => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const spec = CORE_FILES[slot]
  const choose = () => input.current?.click()
  const picker = (
    <input ref={input} type="file" accept={spec.accept} className="hidden"
      onChange={(e) => { const f = e.target.files?.[0]; if (f) onPick(f); e.target.value = '' }} />
  )
  if (file) {
    return (
      <>
        <div className="file-pill">
          <Icon name={icon} size={18} fill className="text-[#00a572]" />
          <span className="n" title={file.fileName}>{file.fileName}</span>
          <span className="z">{(file.size / 1024).toFixed(1)} KB</span>
          <button type="button" className="pill-btn" onClick={choose} disabled={busy} title="Replace">
            <Icon name={busy ? 'progress_activity' : 'swap_horiz'} size={17} className={cn(busy && 'animate-spin')} />
          </button>
          <button type="button" className="pill-btn del" onClick={onClear} disabled={busy} title="Remove">
            <Icon name="close" size={17} />
          </button>
        </div>
        {picker}
      </>
    )
  }
  return (
    <>
      <button type="button" disabled={busy} onClick={choose}
        className={cn('upload-btn', want && 'wanted', over && 'dragover')}
        onDragOver={(e) => { e.preventDefault(); setOver(true) }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => { e.preventDefault(); setOver(false); const f = e.dataTransfer.files[0]; if (f) onPick(f) }}>
        <Icon name={busy ? 'progress_activity' : 'upload_file'} size={18} className={cn(busy && 'animate-spin')} />
        <span className="t">{busy ? 'Uploading…' : want ? <>Upload <b>{want}</b></> : 'Choose a file or drop it here'}</span>
        {!want && !busy && <span className="s">{spec.types}</span>}
      </button>
      {want && !busy && <div className="wanted-note">The imported config names it; the repository does not have it.</div>}
      {picker}
    </>
  )
}

function CoreRow({ label, help, optional, children }: { label: string; help: ReactNode; optional?: boolean; children: ReactNode }) {
  return (
    <div className="core-row">
      <div>
        <div className="core-row-label">{label}</div>
        <div className="core-row-help">{optional && <><span className="opt">Optional</span> · </>}{help}</div>
      </div>
      <div className="min-w-0">{children}</div>
    </div>
  )
}

/** Why a core's name cannot be used: none, or another core has it (case aside). */
function nameIssue(c: Core, cores: Core[]): string | undefined {
  const n = c.name.trim().toLowerCase()
  if (!n) return 'The core needs a name'
  if (cores.some((o) => o.id !== c.id && o.name.trim().toLowerCase() === n)) return 'Another core has this name'
  return undefined
}

/** Step 2: the project's cores. A core is one build of the firmware - its macros, data dictionary
 *  and compile commands (the engine's `cores.<Core>`); each layer picks its core in step 3. */
export function CoresStep({ cores, layers, wanted, uploading, onAdd, onRemove, onChange, onPick }: {
  cores: Core[]
  layers: Layer[]
  wanted: (c: Core) => Wanted
  /** `coreId:slot` of every upload in flight. */
  uploading: Set<string>
  onAdd: () => void
  onRemove: (id: string) => void
  onChange: (id: string, patch: Partial<Core>) => void
  onPick: (id: string, slot: CoreFile, f: File) => void
}) {
  const file = (c: Core, slot: CoreFile, icon: string, want?: string | null) => (
    <FileControl slot={slot} file={c[slot]} want={want} icon={icon} busy={uploading.has(`${c.id}:${slot}`)}
      onPick={(f) => onPick(c.id, slot, f)} onClear={() => onChange(c.id, { [slot]: null })} />
  )
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="memory" size={17} className="text-secondary" />
          <span className="text-on-surface-variant uppercase font-mono text-xs font-medium tracking-[.08em]">
            Cores {cores.length > 0 && `· ${cores.length}`}
          </span>
        </div>
        <button type="button" onClick={onAdd} className="flex items-center gap-1.5 px-3 py-1.5 text-secondary border border-outline-variant rounded-lg hover:bg-surface-container-low transition-colors font-mono text-xs font-medium">
          <Icon name="add" size={15} /> Add Core
        </button>
      </div>

      {cores.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-10 text-center">
          <Icon name="memory" size={36} className="text-on-surface-variant mb-3 opacity-35" />
          <p className="text-on-surface-variant font-mono text-xs font-medium">No cores.</p>
          <p className="text-on-surface-variant mt-1 text-xs">Every layer is parsed without macros or a data dictionary. Click <strong>Add Core</strong> to add one.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {cores.map((c) => {
            const used = layers.filter((l) => l.coreId === c.id).map((l) => l.name)
            const want = wanted(c)
            const issue = nameIssue(c, cores)
            return (
              <div key={c.id} className="core-card">
                <div className="core-card-head">
                  <div className="core-chip-icon"><Icon name="memory" size={17} /></div>
                  <div className="flex-1 min-w-0">
                    <input className={cn('core-name', issue && 'err')} value={c.name} aria-label="Core name"
                      title={issue ?? 'Rename the core'} placeholder="Core name"
                      onChange={(e) => onChange(c.id, { name: e.target.value })} />
                    <div className={cn('core-uses', !used.length && 'none')}>
                      {issue ? <span className="text-error">{issue}</span>
                        : used.length ? <>Used by {used.map((l, i) => <span key={i} className="layer-tag">{l}</span>)}</>
                          : 'No layer uses it yet · pick it for a layer in step 3'}
                    </div>
                  </div>
                  <button type="button" onClick={() => onRemove(c.id)} className="pill-btn del" title="Remove the core">
                    <Icon name="delete" size={18} />
                  </button>
                </div>

                <CoreRow label="Macros" help={<>The <code>-D</code> set for this build</>}>
                  {c.macroMode === 'typed' ? (
                    <>
                      <textarea className="inp mono macro-text" rows={3} value={c.macroText}
                        placeholder={'_CONFIG_CMCORE=1\nPLATFORM=QNX'}
                        onChange={(e) => onChange(c.id, { macroText: e.target.value })} />
                      <div className="flex items-center justify-between gap-3">
                        <span className="core-row-help mt-1.5">One per line: KEY or KEY=VALUE</span>
                        <button type="button" className="switch-link" onClick={() => onChange(c.id, { macroMode: 'file' })}>Upload a file instead</button>
                      </div>
                    </>
                  ) : (
                    <>
                      {file(c, 'macroFile', 'data_object', want?.macros)}
                      <button type="button" className="switch-link" onClick={() => onChange(c.id, { macroMode: 'typed' })}>Type them instead</button>
                    </>
                  )}
                </CoreRow>
                <CoreRow label="Data dictionary" help="Signal names, units, ranges" optional>
                  {file(c, 'dataDictionary', 'menu_book', want?.dataDictionary)}
                </CoreRow>
                <CoreRow label="Compile commands" help="Include paths from the build" optional>
                  {file(c, 'compileCommands', 'terminal', want?.compileCommands)}
                </CoreRow>
              </div>
            )
          })}
        </div>
      )}

      <div className="flex items-start gap-3 p-3.5 bg-surface-container-low border border-outline-variant rounded-xl">
        <Icon name="info" size={18} className="text-secondary flex-shrink-0" />
        <p className="text-on-surface-variant text-xs">Layers built the same way share a core. A layer with no core is parsed without macros or a data dictionary. Paths inside a compile_commands.json come from the build machine and are mapped onto the repository automatically.</p>
      </div>
    </div>
  )
}

/** A core's inputs in one line: the macros file (or how many are typed), dictionary, compile commands. */
function coreSummary(c: Core): string {
  const typed = typedDefines(c.macroText).length
  const macros = c.macroMode === 'typed' ? (typed ? `${typed} typed` : 'no macros') : c.macroFile?.fileName ?? 'no macros'
  return [macros, c.dataDictionary?.fileName ?? 'no dictionary', c.compileCommands?.fileName ?? 'no compile commands'].join(' · ')
}

/** Step 5's Cores card body: each core with the layers built for it, then the layers with none. */
export function CoresReview({ cores, layers }: { cores: Core[]; layers: Layer[] }) {
  const noCore = layers.filter((l) => !l.coreId || !cores.some((c) => c.id === l.coreId)).map((l) => l.name)
  if (!cores.length && !noCore.length) return <p className="px-4 py-3 font-mono text-caption text-outline">No cores</p>
  return (
    <div>
      {cores.map((c) => {
        const used = layers.filter((l) => l.coreId === c.id).map((l) => l.name)
        return (
          <div key={c.id} className="px-4 py-2.5 border-b border-surface-container-low">
            <div className="flex items-center gap-1.5">
              <Icon name="memory" size={14} className="text-secondary" />
              <span className="font-mono text-caption font-bold text-on-surface">{c.name.trim() || '—'}</span>
              <span className={cn('ml-auto font-mono text-label', used.length ? 'text-on-surface-variant' : 'text-[#b45309]')}>
                {used.length ? `used by ${used.join(', ')}` : 'no layer uses it'}
              </span>
            </div>
            <div className="mt-1 ml-5 font-mono text-label text-outline">{coreSummary(c)}</div>
          </div>
        )
      })}
      {noCore.length > 0 && (
        <div className="px-4 py-2.5 font-mono text-label text-outline">No core: {noCore.join(', ')}</div>
      )}
    </div>
  )
}
