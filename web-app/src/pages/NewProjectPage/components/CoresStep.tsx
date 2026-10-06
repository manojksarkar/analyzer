import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Icon } from '../../../components/ui'
import { cn } from '../../../lib/cn'
import type { CoreInputs, UploadedFile } from '../../../types'
import { baseName, CORE_FILES, typedDefines, type Core, type CoreFile, type Layer } from '../helpers'

/** The path an imported config names for each of a core's files. */
type Wanted = CoreInputs<string | null> | undefined

/** What the last folder pick filled: the folder's name, how many files it added, and the files
 *  it did not have (`missing`) or held more than one candidate for (`unsure`), as `Core: name`. */
export interface FolderResult { folder: string; added: number; missing: string[]; unsure: string[] }

/** Above the cores, while an imported config still names files: one folder pick fills every one
 *  it holds. Only those files are sent; the rest of the folder stays on the user's machine. */
function FolderFill({ open, result, busy, onPick }: {
  open: number
  result: FolderResult | null
  busy: boolean
  onPick: (files: File[]) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  // Not in React's input attributes: set on the element itself.
  useEffect(() => { input.current?.setAttribute('webkitdirectory', '') }, [])
  const left = [...(result?.missing ?? []), ...(result?.unsure ?? [])]
  return (
    <div className="p-3.5 border border-dashed border-outline-variant rounded-xl bg-surface-container-lowest">
      <div className="flex items-center gap-3">
        <Icon name="folder_open" size={18} className="text-secondary flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm text-on-surface">
            {!open ? 'Every file the config names is here'
              : result ? `${open} file${open === 1 ? '' : 's'} the config names ${open === 1 ? 'is' : 'are'} still missing`
                : `The config names ${open} file${open === 1 ? '' : 's'} for these cores`}
          </p>
          <p className="text-caption text-on-surface-variant mt-0.5">
            Pick the folder that holds them: each is matched by its name and path, and only those files are sent.
          </p>
        </div>
        {open > 0 && (
          <button type="button" disabled={busy} onClick={() => input.current?.click()}
            className="flex items-center gap-1.5 px-3 py-1.5 border border-secondary text-secondary rounded-lg hover:bg-surface-container-low transition-colors flex-shrink-0 disabled:opacity-60 font-mono text-caption font-semibold">
            <Icon name={busy ? 'progress_activity' : 'drive_folder_upload'} size={14} className={cn(busy && 'animate-spin')} />
            {busy ? 'Uploading…' : 'Choose folder'}
          </button>
        )}
        <input ref={input} type="file" multiple className="hidden"
          onChange={(e) => { const fs = [...(e.target.files ?? [])]; e.target.value = ''; if (fs.length) onPick(fs) }} />
      </div>
      {result && !busy && (
        <div className="mt-2 ml-[30px] space-y-0.5 text-caption">
          <p className="flex items-center gap-1 text-success">
            <Icon name="check_circle" size={13} fill />
            <span><b className="font-mono">{result.folder}</b>: {result.added} file{result.added === 1 ? '' : 's'} added</span>
          </p>
          {result.missing.length > 0 && (
            <p className="text-warn">Not in it: {result.missing.join(', ')}</p>
          )}
          {result.unsure.length > 0 && (
            <p className="text-warn">More than one file fits, so none was taken: {result.unsure.join(', ')}</p>
          )}
          {left.length > 0 && <p className="text-on-surface-variant">Upload {left.length === 1 ? 'it' : 'them'} below.</p>}
        </div>
      )}
    </div>
  )
}

/** One input's control: an upload button, or - once there is a file - a pill with its name,
 *  size, Replace and Remove. A file an imported config names asks for itself by name. */
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
          <Icon name={icon} size={18} fill className="text-success" />
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
        <span className="t" title={want ?? undefined}>{busy ? 'Uploading…' : want ? <>Upload <b>{baseName(want)}</b></> : 'Choose a file or drop it here'}</span>
        {!want && !busy && <span className="s">{spec.types}</span>}
      </button>
      {want && !busy && <div className="wanted-note">The imported config names it: pick its folder above, or upload it here.</div>}
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
export function CoresStep({ cores, layers, wanted, openFiles, folder, folderBusy, uploading, onAdd, onRemove, onChange, onPick, onFolder }: {
  cores: Core[]
  layers: Layer[]
  wanted: (c: Core) => Wanted
  /** How many files an imported config names that no core has yet. */
  openFiles: number
  /** The last folder pick's result; null before one, or when there was no config to fill from. */
  folder: FolderResult | null
  folderBusy: boolean
  /** `coreId:slot` of every upload in flight. */
  uploading: Set<string>
  onAdd: () => void
  onRemove: (id: string) => void
  onChange: (id: string, patch: Partial<Core>) => void
  onPick: (id: string, slot: CoreFile, f: File) => void
  onFolder: (files: File[]) => void
}) {
  const file = (c: Core, slot: CoreFile, icon: string, want?: string | null) => (
    <FileControl slot={slot} file={c[slot]} want={want} icon={icon} busy={uploading.has(`${c.id}:${slot}`)}
      onPick={(f) => onPick(c.id, slot, f)} onClear={() => onChange(c.id, { [slot]: null })} />
  )
  // The optional inputs stay out of the way until they have a file, a config asks for one, or
  // the user adds one.
  const [opened, setOpened] = useState<Set<string>>(new Set())
  const shows = (c: Core, slot: CoreFile, want?: string | null) =>
    !!c[slot] || !!want || uploading.has(`${c.id}:${slot}`) || opened.has(`${c.id}:${slot}`)
  const open = (c: Core, slot: CoreFile) => setOpened((p) => new Set(p).add(`${c.id}:${slot}`))
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

      {(openFiles > 0 || folder) && <FolderFill open={openFiles} result={folder} busy={folderBusy} onPick={onFolder} />}

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
                {shows(c, 'dataDictionary', want?.dataDictionary) && (
                  <CoreRow label="Data dictionary" help="Signal names, units, ranges" optional>
                    {file(c, 'dataDictionary', 'menu_book', want?.dataDictionary)}
                  </CoreRow>
                )}
                {shows(c, 'compileCommands', want?.compileCommands) && (
                  <CoreRow label="Compile commands" help="Include paths from the build" optional>
                    {file(c, 'compileCommands', 'terminal', want?.compileCommands)}
                  </CoreRow>
                )}
                {(!shows(c, 'dataDictionary', want?.dataDictionary) || !shows(c, 'compileCommands', want?.compileCommands)) && (
                  <div className="flex items-center gap-4 px-4 py-2.5 border-t border-surface-container-low">
                    <span className="font-mono text-label text-outline uppercase tracking-[.06em]">Optional</span>
                    {!shows(c, 'dataDictionary', want?.dataDictionary) && (
                      <button type="button" className="switch-link mt-0 flex items-center gap-1" onClick={() => open(c, 'dataDictionary')}>
                        <Icon name="add" size={13} />Data dictionary
                      </button>
                    )}
                    {!shows(c, 'compileCommands', want?.compileCommands) && (
                      <button type="button" className="switch-link mt-0 flex items-center gap-1" onClick={() => open(c, 'compileCommands')}>
                        <Icon name="add" size={13} />Compile commands
                      </button>
                    )}
                  </div>
                )}
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
              <span className={cn('ml-auto font-mono text-label', used.length ? 'text-on-surface-variant' : 'text-warn')}>
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
