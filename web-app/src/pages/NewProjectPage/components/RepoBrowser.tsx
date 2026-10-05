import { Fragment, useEffect, useRef, useState } from 'react'
import { Icon } from '../../../components/ui'
import { APP_NAME } from '../../../constants/branding'
import { useRepositoryWizard } from '../../../hooks/useRepositoryWizard'
import { ApiError } from '../../../lib/http'
import { cn } from '../../../lib/cn'
import type { LocalFolder, LocalFolders } from '../../../types'
import { browseStart, folderCrumbs } from '../helpers'

/* Local path: Browse - the folders of the server ArtiFex runs on, one folder at a time (GET
   /repositories/local-folders). A browser cannot give a full path from the user's own PC, and git
   runs on the server: so the server's folders. A plain folder opens; only a git repository is
   picked, and a double-click picks and uses it. It opens where the repository field points. */

type Load = { state: 'loading' } | { state: 'error'; message: string } | { state: 'ready'; listing: LocalFolders }
/** `pick`: the path to pick when it is a repository of the folder read; `fallBack`: a folder the
 *  server refuses or does not have opens the top list instead. */
interface ReadOpts { pick?: string; fallBack?: boolean }

const CRUMB = 'inline-flex items-center gap-1 px-1.5 py-0.5 rounded-lg font-mono text-caption font-medium text-secondary hover:bg-surface-container-low transition-colors'
const CRUMB_LAST = 'text-on-surface font-semibold'
const ROW = 'w-full flex items-center gap-2 px-2.5 py-[7px] rounded-[6px] cursor-pointer select-none text-left font-mono text-xs leading-[18px] text-on-surface hover:bg-surface-container-low transition-colors'
const ROW_PICKED = 'bg-surface-container hover:bg-surface-container text-secondary font-semibold'

/** The folder at `path`: as written, or in another case for a Windows path (D:/Src is D:/src). */
function findFolder(folders: LocalFolder[], path: string): LocalFolder | undefined {
  return folders.find((f) => f.path === path)
    ?? (/^[A-Za-z]:/.test(path) ? folders.find((f) => f.path.toLowerCase() === path.toLowerCase()) : undefined)
}

export function RepoBrowser({ start, onUse, onClose }: {
  /** What the repository field holds: Browse opens in the folder above it, that repository picked. */
  start: string
  /** "Use this repository" (or a double-click): the repository's full path. */
  onUse: (path: string) => void
  onClose: () => void
}) {
  const repo = useRepositoryWizard()
  const [first] = useState(() => browseStart(start))
  // The folder shown, or being read ('' = the top list).
  const [at, setAt] = useState(first?.folder ?? '')
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  // The repository picked, a full path.
  const [picked, setPicked] = useState('')
  // The top list, once read: where each breadcrumb begins.
  const [roots, setRoots] = useState<LocalFolder[] | null>(null)
  // The newest read wins; Retry repeats the last one.
  const seq = useRef(0)
  const lastRead = useRef<{ path: string; opts: ReadOpts }>({ path: '', opts: {} })
  const panel = useRef<HTMLElement>(null)

  // State changes only when the answer comes (the effect below reads the first folder).
  function read(path: string, opts: ReadOpts = {}): Promise<void> {
    const n = ++seq.current
    lastRead.current = { path, opts }
    return repo.localFolders(path).then((listing) => {
      if (n !== seq.current) return
      setAt(listing.path)
      setLoad({ state: 'ready', listing })
      if (!listing.path) setRoots(listing.folders)
      const hit = opts.pick ? findFolder(listing.folders, opts.pick) : undefined
      if (hit?.git) setPicked(hit.path)
    }, (e: unknown) => {
      if (n !== seq.current) return
      if (opts.fallBack && e instanceof ApiError && [400, 403, 404].includes(e.status)) { go(''); return }
      setLoad({ state: 'error', message: (e as Error).message || 'The folders could not be read.' })
    })
  }
  function go(path: string, opts: ReadOpts = {}) {
    setAt(path)
    setPicked('')
    setLoad({ state: 'loading' })
    void read(path, opts)
  }

  // Once: the folder above where the field points (or the top list).
  useEffect(() => {
    void read(first?.folder ?? '', first ? { pick: first.pick, fallBack: true } : {})
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for where the field pointed on opening
  }, [])

  // Opened deep in a server that limits the picker to some folders: read the top list too, so the
  // breadcrumb starts at the allowed folder, not at a drive the server refuses.
  const listing = load.state === 'ready' ? load.listing : null
  const needRoots = !roots && !!listing?.limited && !!listing.path
  useEffect(() => {
    if (!needRoots) return
    let live = true
    repo.localFolders('').then((l) => { if (live) setRoots(l.folders) }, () => { /* the crumbs keep the path's own parts */ })
    return () => { live = false }
  }, [needRoots, repo])

  // Esc closes; focus moves into the panel, and back where it was when the panel closes.
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null
    panel.current?.focus()
    return () => { before?.focus?.() }
  }, [])

  const crumbs = folderCrumbs(at, roots)
  const top = !at

  return (
    <>
      <div className="fixed inset-0 z-[99] bg-[rgba(4,22,39,.25)]" onClick={onClose} />
      <aside
        ref={panel}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label="Choose a git repository on the server"
        className="fixed top-0 right-0 h-screen bg-white border-l border-outline-variant z-[100] flex flex-col w-[380px] shadow-[-4px_0_24px_rgba(4,22,39,.12)] outline-none"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-outline-variant flex-shrink-0">
          <div>
            <h3 className="text-on-surface font-sans text-sm font-semibold">Choose a repository</h3>
            <p className="text-on-surface-variant mt-0.5 text-caption">Folders on the server {APP_NAME} runs on. Only a git repository can be picked.</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="p-1.5 text-on-surface-variant hover:text-on-surface hover:bg-surface-container rounded-lg transition-colors">
            <Icon name="close" size={20} />
          </button>
        </div>

        {/* Where we are: each part goes back there. */}
        <nav aria-label="Folder" className="flex flex-wrap items-center gap-0.5 px-4 py-2.5 border-b border-outline-variant flex-shrink-0">
          <button type="button" onClick={() => go('')} className={cn(CRUMB, top && CRUMB_LAST)}>
            <Icon name="dns" size={14} />This server
          </button>
          {crumbs.map((c, i) => (
            <Fragment key={c.path}>
              <span className="text-outline text-caption">›</span>
              <button type="button" onClick={() => go(c.path)} className={cn(CRUMB, i === crumbs.length - 1 && CRUMB_LAST)}>{c.name}</button>
            </Fragment>
          ))}
        </nav>

        {/* The folder's folders: a plain one opens, a git repository is picked (double-click: picked
            and used). Picking only marks the row: the rows stay, so a double-click's second click
            lands on the same one. */}
        <div className="flex-1 overflow-y-auto px-2 py-2">
          {load.state === 'loading' ? (
            <p className="flex items-center gap-2 px-2.5 py-4 font-mono text-caption text-on-surface-variant">
              <Icon name="progress_activity" size={15} className="animate-spin" />
              Reading the folders…
            </p>
          ) : load.state === 'error' ? (
            <div role="alert" className="m-1 flex items-start gap-2 p-3 bg-error-container border border-error rounded-xl text-xs text-on-error-container">
              <Icon name="error" size={15} fill className="flex-shrink-0 mt-px text-error" />
              <span className="flex-1 min-w-0 break-words">{load.message}</span>
              <button type="button" onClick={() => go(lastRead.current.path, lastRead.current.opts)}
                className="flex-shrink-0 font-mono text-caption font-bold uppercase tracking-[.06em] text-secondary hover:underline">
                Retry
              </button>
            </div>
          ) : !load.listing.folders.length ? (
            <div className="px-2.5 py-4 text-center text-xs leading-4 text-outline">No folders here</div>
          ) : (
            <>
              {load.listing.folders.map((f) => f.git ? (
                <button key={f.path} type="button" title={f.path} aria-pressed={f.path === picked}
                  onClick={() => setPicked(f.path)} onDoubleClick={() => onUse(f.path)}
                  className={cn(ROW, f.path === picked && ROW_PICKED)}>
                  <Icon name="source" size={16} className="text-[#006e45]" />
                  <span className="flex-1 min-w-0 truncate">{f.name}</span>
                  <span className="px-1.5 rounded-[3px] bg-[#d6f5ea] text-[#006e45] font-mono text-label font-semibold">git</span>
                  <Icon name="check" size={16} className={f.path === picked ? undefined : 'invisible'} />
                </button>
              ) : (
                <button key={f.path} type="button" title={f.path} onClick={() => go(f.path)} className={ROW}>
                  <Icon name={top ? 'hard_drive' : 'folder'} size={16} className={top ? 'text-outline' : 'text-secondary'} />
                  <span className="flex-1 min-w-0 truncate">{top ? f.name : `${f.name}/`}</span>
                  <Icon name="chevron_right" size={16} className="text-outline" />
                </button>
              ))}
              {load.listing.truncated && (
                <p className="px-2.5 pt-2 pb-1 font-mono text-caption text-outline">
                  Showing the first {load.listing.folders.length.toLocaleString('en-US')} folders
                </p>
              )}
            </>
          )}
        </div>

        <div className="px-4 py-3 border-t border-outline-variant flex-shrink-0 space-y-2.5">
          <p className={cn('font-mono text-caption font-medium truncate', picked ? 'text-on-surface' : 'text-outline')}>
            {picked || 'Pick a git repository'}
          </p>
          <div className="flex gap-3">
            <button type="button" onClick={onClose} className="px-4 py-2 border border-outline-variant text-on-surface-variant rounded-lg hover:bg-surface-container transition-colors font-mono text-xs font-medium">Cancel</button>
            <button type="button" onClick={() => { if (picked) onUse(picked) }} disabled={!picked}
              className="flex-1 py-2 bg-secondary text-on-secondary rounded-lg hover:bg-secondary-container transition-colors font-mono text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-secondary">
              Use this repository
            </button>
          </div>
        </div>
      </aside>
    </>
  )
}
