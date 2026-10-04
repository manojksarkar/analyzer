import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateProject } from '../../hooks/useProjects'
import { useRepositoryWizard } from '../../hooks/useRepositoryWizard'
import { useAuthStore } from '../../store/auth'
import { CodeText, Icon, BrandMark, toast } from '../../components/ui'
import { cn } from '../../lib/cn'
import { APP_NAME, APP_TAGLINE } from '../../constants/branding'
import type { CreateProjectInput, RepoEntry, OrgUser } from '../../services/api'
import type { ConfigPreview } from '../../types'
import { ConfigImport } from './components/ConfigImport'
import { CoresReview, CoresStep, type FolderResult } from './components/CoresStep'
import { Readiness, type ReadinessItem } from './components/Readiness'
import { clearDraft, loadDraft, saveDraft } from './draft'
import {
  assignmentsOf, baseName, CORE_FILES, coreInput, coreProblems, draftToCores, draftToLayers, fitsCoreFile, indexTree,
  matchFolder, newCore, nextCoreName, openWants, ownerOf, pathProblems, settingsSummary, typedDefines,
  type Comp, type Core, type CoreFile, type Group, type Layer, type Member, type Role, type WantedFile,
} from './helpers'

// Rail entries — short title + sub, mirroring the design's step rail.
const STEPS = [
  { title: 'Project & Repository', sub: 'Name, source path' },
  { title: 'Cores',                sub: 'Macros & dictionary per core' },
  { title: 'Architecture',         sub: 'Layers & groups' },
  { title: 'Team & Access',        sub: 'Optional · add people later' },
  { title: 'Review & Initialize',  sub: 'Confirm & create project' },
]

// Per-step content header (longer description shown above the form fields).
const STEP_HEADERS = [
  { title: 'Project & Repository', sub: 'Name the project and connect your source repository.' },
  { title: 'Cores',                sub: 'A core is one build of the firmware, with its own macros, data dictionary and compile commands. Each layer picks its core in the next step.' },
  { title: 'Architecture Mapping', sub: 'Map layers and groups. Components are discovered automatically from source folders.' },
  { title: 'Team & Access',        sub: 'Add team members and assign their role. More members can be added later from the Team page.' },
  { title: 'Review & Initialize',  sub: 'Confirm every setting before the first analysis run.' },
]

// The action bar's note for each step: what is required, and what can be left out.
const STEP_HINTS = [
  'Name, repository and branch are required',
  'Optional - a layer with no core is parsed without macros',
  'At least one component with files is required',
  'Optional - people can be added later from Team',
  'Nothing is created until you initialize',
]

const TREE_CB = 'w-3.5 h-3.5 accent-secondary cursor-pointer flex-shrink-0'

type TestTone = 'neutral' | 'error' | 'ok'

// The source tree comes from the real POST /repositories/browse endpoint
// (api/routes/repositories.py) as a nested RepoEntry[] — folders carry
// `children`, files don't. Fetched once after a successful Test Connection.
const isFolder = (n: RepoEntry) => n.type === 'folder'

// Inline loader for the source-tree panels while the repo is being browsed.
function TreeLoading() {
  return (
    <div className="flex items-center gap-2 px-2 py-6 text-on-surface-variant font-mono text-caption">
      <Icon name="progress_activity" size={15} className="animate-spin" />
      Loading repository tree…
    </div>
  )
}
const descendantFiles = (n: RepoEntry): string[] =>
  n.type === 'file' ? [n.path] : (n.children ?? []).flatMap(descendantFiles)

/** Folders-only projection of the source tree, for the Select-Folder picker. */
function foldersOnly(nodes: RepoEntry[]): RepoEntry[] {
  return nodes.filter(isFolder).map((n) => ({ ...n, children: foldersOnly(n.children ?? []) }))
}

/** Find the folder/file node at `path` anywhere in the tree. */
function findNode(nodes: RepoEntry[], path: string): RepoEntry | null {
  const norm = path.replace(/\/+$/, '')
  for (const n of nodes) {
    if (n.path === norm) return n
    if (n.type === 'folder') {
      const found = findNode(n.children ?? [], norm)
      if (found) return found
    }
  }
  return null
}

/** Derive a project-root label from the Step-1 repo URL (e.g. …/vcu-firmware.git → "vcu-firmware"). */
function repoRootName(url: string): string {
  const t = url.trim().replace(/\.git$/i, '').replace(/[/\\]+$/, '')
  if (!t) return 'project-root'
  return t.split(/[/\\]/).pop() || 'project-root'
}

// Unique across reloads too: a restored draft keeps its ids, and a new one must not repeat them.
let _uid = 0
const UID_RUN = Math.random().toString(36).slice(2, 7)
const uid = () => `id${UID_RUN}${++_uid}`
const plural = (n: number, w: string) => `${n} ${w}${n !== 1 ? 's' : ''}`

function initialsOf(label: string) {
  return label.split(' ').map((w) => w[0] || '').join('').slice(0, 2).toUpperCase()
}
function memberInitials(m: { name?: string; email: string }) {
  if (m.name) return initialsOf(m.name)
  const parts = m.email.split('@')[0].split(/[._-]/)
  return (parts.length >= 2 ? parts[0][0] + parts[1][0] : m.email.slice(0, 2)).toUpperCase()
}

/* ─── Shared header ─────────────────────────────────────────────────── */
function PageHeader({ step, onBack, backLabel }: { step: number; onBack: () => void; backLabel: string }) {
  return (
    <header className="h-14 flex-shrink-0 flex items-center justify-between px-6 bg-white border-b border-outline-variant z-40">
      <div className="flex items-center gap-3">
        <BrandMark size={32} className="flex-shrink-0 text-secondary" />
        <div>
          <h1 className="text-primary font-bold tracking-tight font-sans text-xl leading-[1.2]">{APP_NAME}</h1>
          <p className="text-on-surface-variant uppercase mt-0.5 font-mono text-caption font-medium tracking-[0.08em]">{APP_TAGLINE}</p>
        </div>
      </div>

      <div className="absolute left-1/2 -translate-x-1/2">
        <span className="text-on-surface-variant font-mono text-xs font-medium tracking-[0.02em]">
          Step {step} of {STEPS.length}
        </span>
      </div>

      <button onClick={onBack} className="flex items-center gap-1.5 text-sm text-on-surface-variant hover:text-on-surface transition-colors">
        <Icon name="arrow_back" size={18} />
        {backLabel}
      </button>
    </header>
  )
}

/* ─── Step rail ─────────────────────────────────────────────────────── */
function StepRail({
  cur, done, issues, onClose, onGo,
}: { cur: number; done: Set<number>; issues: Set<number>; onClose: () => void; onGo: (n: number) => void }) {
  const pct = Math.round((done.size / STEPS.length) * 100)
  return (
    <aside className="w-60 flex-shrink-0 bg-white border-r border-outline-variant flex flex-col overflow-y-auto">
      <div className="px-4 pt-4 pb-3 border-b border-outline-variant">
        <div className="flex items-center justify-between mb-1.5">
          <p className="text-on-surface-variant uppercase font-mono text-caption font-medium tracking-[0.10em]">Setup Progress</p>
          <button onClick={onClose} title="Cancel" className="text-on-surface-variant hover:text-on-surface transition-colors">
            <Icon name="close" size={18} />
          </button>
        </div>
        <div className="flex items-center gap-3 mt-2">
          <div className="flex-1 bg-surface-container rounded-full overflow-hidden h-[5px]">
            {/* eslint-disable-next-line no-restricted-syntax -- progress width is data-driven */}
            <div className="bg-secondary h-full rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
          </div>
          <span className="text-on-surface-variant whitespace-nowrap font-mono text-caption font-medium">{done.size} / {STEPS.length}</span>
        </div>
      </div>

      <div className="flex-1 px-4 py-5">
        {STEPS.map((s, i) => {
          const n = i + 1
          const state = done.has(n) ? 'done' : n === cur ? 'active' : 'pending'
          const clickable = n < cur || done.has(n)
          return (
            <div key={n} className={cn('step-li', clickable && 'cursor-pointer')} onClick={() => clickable && onGo(n)}>
              <div className={`step-dot ${state}`}>
                {state === 'done'
                  ? <Icon name="check" size={14} fill />
                  : n}
                {issues.has(n) && <span className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-error border-2 border-white" />}
              </div>
              <div className="pt-[3px]">
                <p className={cn('font-mono text-xs leading-[1.2]', n === cur ? 'text-secondary font-semibold' : done.has(n) ? 'text-on-surface font-medium' : 'text-on-surface-variant font-medium')}>{s.title}</p>
                <p className={cn('font-mono text-caption mt-0.5', issues.has(n) ? 'text-error' : n === cur ? 'text-secondary' : 'text-outline')}>
                  {issues.has(n) ? 'Needs a fix' : s.sub}
                </p>
              </div>
            </div>
          )
        })}
      </div>

      <div className="px-4 pb-4">
        <div className="flex items-start gap-2.5 p-3 bg-surface-container-low border border-outline-variant rounded-xl">
          <Icon name="admin_panel_settings" size={14} className="text-secondary flex-shrink-0 mt-0.5" />
          <p className="text-on-surface-variant leading-snug font-mono text-caption font-medium">Admin-only setup. Developers gain access after initialization.</p>
        </div>
      </div>
    </aside>
  )
}

/* ─── Step content header ───────────────────────────────────────────── */
function StepHeader({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="pb-4 border-b border-outline-variant">
      <h2 className="text-on-surface mb-1 font-sans text-2xl leading-[32px] tracking-[-0.01em] font-semibold">{title}</h2>
      <p className="text-on-surface-variant text-sm leading-5">{sub}</p>
    </div>
  )
}

/* ─── What stops a step, inside the step ────────────────────────────── */
function StepIssues({ items }: { items: string[] }) {
  if (!items.length) return null
  return (
    <div role="alert" className="p-3.5 bg-error-container border border-error rounded-xl">
      <p className="flex items-center gap-2 font-mono text-xs font-semibold text-on-error-container">
        <Icon name="error" size={15} fill className="text-error" />
        {items.length === 1 ? 'One thing' : `${items.length} things`} to fix before you continue
      </p>
      <ul className="mt-2 ml-6 space-y-1 list-disc">
        {items.map((t, i) => <li key={i} className="text-xs text-on-error-container leading-[1.45]"><CodeText text={t} /></li>)}
      </ul>
    </div>
  )
}

/* ─── Wizard ────────────────────────────────────────────────────────── */
function WizardView({
  onCancel, onSubmit, submitting, onStepChange,
}: { onCancel: () => void; onSubmit: (data: CreateProjectInput) => void; submitting: boolean; onStepChange: (n: number) => void }) {
  const repo = useRepositoryWizard()
  // A reload keeps the wizard where it was (this tab's draft, read once). A private repository's
  // token is never kept: that draft opens on step 1 to have it typed again, its later steps one
  // click away on the rail.
  const [draft] = useState(loadDraft)
  const reenterToken = !!draft?.tokenUsed && !!draft.repoUrl
  // 1-based step + `done` set (steps advanced past) — drives the rail + bar.
  const [cur, setCur] = useState(() =>
    draft && !reenterToken ? Math.min(Math.max(Math.round(draft.step), 1), STEPS.length) : 1)
  const [done, setDone] = useState<Set<number>>(() => new Set(draft?.done ?? []))
  // Steps where Continue was tried: their problems show inside the step from then on.
  const [attempted, setAttempted] = useState<Set<number>>(new Set())
  const scrollRef = useRef<HTMLDivElement>(null)
  // The pinned "self" row uses the real logged-in user (admin/creator).
  const authUser = useAuthStore((s) => s.user)
  const me = { name: authUser?.name ?? 'You', email: authUser?.email ?? '', initials: authUser?.initials ?? 'YOU' }

  // ── Step 1: project & repository ──
  const [name, setName] = useState(draft?.name ?? '')
  const [repoUrl, setRepoUrl] = useState(draft?.repoUrl ?? '')
  const [token, setToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [tokenOpen, setTokenOpen] = useState(reenterToken)
  const [branch, setBranch] = useState(draft?.branch ?? '')
  const [branches, setBranches] = useState<string[]>([])
  // Filters the branch list - a repository can have hundreds. The picked branch always stays listed.
  const [branchQuery, setBranchQuery] = useState('')
  const shownBranches = useMemo(() => {
    const q = branchQuery.trim().toLowerCase()
    if (!q) return branches
    const hits = branches.filter((b) => b.toLowerCase().includes(q))
    return branch && !hits.includes(branch) ? [branch, ...hits] : hits
  }, [branches, branchQuery, branch])
  const [testState, setTestState] = useState<'idle' | 'connecting' | 'connected'>('idle')
  const [testMsg, setTestMsg] = useState<{ text: string; tone: TestTone } | null>(() => reenterToken
    ? { text: 'Enter the access token again and test the connection: a token is never kept.', tone: 'neutral' }
    : null)
  const [errs, setErrs] = useState<{ name?: boolean; repo?: boolean; branch?: boolean }>({})
  // Source tree fetched from /repositories/browse after a successful connection.
  const [repoTree, setRepoTree] = useState<RepoEntry[]>([])
  // True while the (blobless) clone + tree fetch is in flight — drives the
  // loaders in the Add-Component panel and the folder picker.
  const [repoTreeLoading, setRepoTreeLoading] = useState(false)
  // Which branch the tree is of, and whether reading it failed: every path of the new project is
  // checked against it before the project is created.
  const [repoTreeFor, setRepoTreeFor] = useState('')
  const [repoTreeFailed, setRepoTreeFailed] = useState(false)
  // The newest request wins: a slower answer for a branch or repository the user has already left
  // is dropped (the tree, and the check of an imported config).
  const treeSeq = useRef(0)
  const checkSeq = useRef(0)

  // ── Config import (step 1, optional) — fills every step it can ──
  // A restored import has no `text` (a draft never keeps the file): it is not checked again.
  const [imported, setImported] = useState<{ text: string; fileName: string; preview: ConfigPreview } | null>(
    () => (draft?.imported ? { text: '', ...draft.imported } : null))
  const [importBusy, setImportBusy] = useState(false)
  // What the config also named but the user's own value was kept for (e.g. "project name").
  const [importKept, setImportKept] = useState<string[]>(draft?.importKept ?? [])
  // A check of the import against the repository is under way (a network round trip or two).
  const [importChecking, setImportChecking] = useState(false)
  // The branch the config names (or a restored draft's), picked once Test Connection lists the branches.
  const [preferredBranch, setPreferredBranch] = useState(draft?.branch ?? '')
  // True once the user edits the imported architecture: the re-check after Test Connection then
  // leaves the tree alone and only refreshes the report.
  const archEdited = useRef(draft?.archEdited ?? false)
  const [archChanged, setArchChanged] = useState(draft?.archEdited ?? false)
  function markArchEdited(edited = true) { archEdited.current = edited; setArchChanged(edited) }

  // ── Step 2: cores ──
  // One to start with: most projects are one build. `coresRef` is always the latest list, so an
  // import's layers find the cores the same import just made (state lags a render behind).
  const [cores, setCoresState] = useState<Core[]>(() => draft?.cores ?? [newCore(uid(), 'Core1')])
  const coresRef = useRef(cores)
  function updateCores(fn: (prev: Core[]) => Core[]) {
    const next = fn(coresRef.current)
    coresRef.current = next
    setCoresState(next)
  }
  // `coreId:slot` of every core file being uploaded.
  const [uploading, setUploading] = useState<Set<string>>(new Set())
  // What the last folder pick filled in, and whether its uploads are still running.
  const [folderResult, setFolderResult] = useState<FolderResult | null>(null)
  const [folderBusy, setFolderBusy] = useState(false)

  // ── Step 3: architecture ──
  const [layers, setLayers] = useState<Layer[]>(draft?.layers ?? [])
  const [addLayerOpen, setAddLayerOpen] = useState(false)
  const [newLayerName, setNewLayerName] = useState('')
  const [newLayerPath, setNewLayerPath] = useState('')
  const [newLayerCore, setNewLayerCore] = useState('')
  // The last removal, until undone, replaced, or the user leaves the step.
  const [lastRemoved, setLastRemoved] = useState<{ label: string; layers: Layer[]; assignments: Record<string, string> } | null>(null)
  const [inlineAdd, setInlineAdd] = useState<{ parentId: string } | null>(null)
  const [inlineVal, setInlineVal] = useState('')
  // Add-Component right panel
  const [compPanel, setCompPanel] = useState<{ layerId: string; groupId: string } | null>(null)
  const [compName, setCompName] = useState('')
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set())
  const [treeOpen, setTreeOpen] = useState<Record<string, boolean>>({ 'src/': true })
  const [fileAssignments, setFileAssignments] = useState<Record<string, string>>(draft?.fileAssignments ?? {})
  // Browse folder-picker
  type FpTarget = { kind: 'new-layer-path' } | { kind: 'lib-path'; layerId: string; index: number }
  const [fpTarget, setFpTarget] = useState<FpTarget | null>(null)
  const [fpSelected, setFpSelected] = useState('')
  const [fpOpen, setFpOpen] = useState<Record<string, boolean>>({})

  // ── Step 4: team ──
  const [members, setMembers] = useState<Member[]>(draft?.members ?? [])
  const [addMemberOpen, setAddMemberOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [inviteRole, setInviteRole] = useState<Role>('Developer')
  const [rolesOpen, setRolesOpen] = useState(false)
  const [reviewTreeOpen, setReviewTreeOpen] = useState(false)
  // Org directory results from GET /users/search (debounced as the user types).
  const [searchResults, setSearchResults] = useState<OrgUser[]>([])
  const [searchLoading, setSearchLoading] = useState(false)

  // Reset scroll to top on step change, and report active step up to the top bar.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
    onStepChange(cur)
  }, [cur, onStepChange])
  // Keep this tab's draft as it changes (draft.ts: never the token, nor the imported file's text).
  const tokenUsed = tokenOpen || !!token
  useEffect(() => {
    saveDraft({
      step: cur, done: [...done], name, repoUrl, branch, tokenUsed, cores, layers, fileAssignments, members,
      imported: imported ? { fileName: imported.fileName, preview: imported.preview } : null,
      importKept, archEdited: archChanged,
    })
  }, [cur, done, name, repoUrl, branch, tokenUsed, cores, layers, fileAssignments, members, imported, importKept, archChanged])
  // A restored public repository is connected again by itself: its branches and files are not
  // kept, and steps 3 and 5 check every path against them. A private one waits for its token.
  useEffect(() => {
    if (draft?.repoUrl && !reenterToken) void testConnection()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for the draft this page opened with
  }, [])
  // An undo is offered for a while, not forever.
  useEffect(() => {
    if (!lastRemoved) return
    const t = window.setTimeout(() => setLastRemoved(null), 10000)
    return () => window.clearTimeout(t)
  }, [lastRemoved])

  /* ── Step 1 helpers ── */
  function repoChanged() {
    setTestState('idle')
    setTestMsg(null)
    setBranches([])
    setBranch('')
    setBranchQuery('')
    setRepoTree([])
    treeSeq.current++; checkSeq.current++                  // drop answers about the old one
    setRepoTreeFor(''); setRepoTreeFailed(false); setImportChecking(false)
    // An import checked against the old repository is not checked against this one.
    setImported((p) => (p?.preview.repositoryChecked ? { ...p, preview: { ...p.preview, repositoryChecked: false } } : p))
  }
  // Load the source tree for a specific branch/ref (architecture + folder pickers).
  // Re-run whenever the selected branch changes so the tree matches the branch.
  async function loadRepoTree(ref: string) {
    const seq = ++treeSeq.current
    setRepoTreeLoading(true); setRepoTreeFailed(false)
    try {
      // refresh: the branch as it is now, not the snapshot cached when it was first opened.
      const nodes = await repo.browse(repoUrl.trim(), ref || undefined, '', token.trim() || undefined, true)
      if (seq !== treeSeq.current) return
      setRepoTree(nodes); setRepoTreeFor(ref)
    } catch {
      if (seq !== treeSeq.current) return
      setRepoTree([]); setRepoTreeFor(''); setRepoTreeFailed(true)
    } finally {
      if (seq === treeSeq.current) setRepoTreeLoading(false)
    }
  }
  async function testConnection() {
    if (!repoUrl.trim()) {
      setErrs((p) => ({ ...p, repo: true }))
      return
    }
    setTestState('connecting')
    setTestMsg({ text: 'Connecting…', tone: 'neutral' })
    try {
      const res = await repo.testConnection({
        repo_url: repoUrl.trim(),
        access_token: token.trim() || undefined,
      })
      if (!res.connected) {
        setTestState('idle')
        setTestMsg({ text: res.message || 'Could not connect to the repository.', tone: 'error' })
        setBranches([]); setBranch(''); setRepoTree([])
        return
      }
      // An imported config's branch wins when the repository has it.
      const initialBranch = (preferredBranch && res.branches.includes(preferredBranch) ? preferredBranch : '')
        || res.defaultBranch || res.branches[0] || ''
      setBranches(res.branches)
      setBranchQuery('')
      setBranch(initialBranch)
      setTestState('connected')
      setTestMsg({ text: res.message, tone: 'ok' })
      // Pre-fetch the source tree for the architecture + folder pickers.
      await loadRepoTree(initialBranch)
      // An imported config's paths were taken as written: check them against this repository.
      if (imported && !imported.preview.repositoryChecked) {
        await checkImportAgainstRepo(imported, initialBranch, !archEdited.current)
      }
    } catch (e) {
      setTestState('idle')
      setTestMsg({ text: (e as Error).message || 'Connection failed.', tone: 'error' })
      setBranches([]); setBranch(''); setRepoTree([])
    }
  }

  /* ── Config import — POST /projects/config/preview fills what it can ── */
  async function importConfig(file: File) {
    setImportBusy(true)
    try {
      const text = await file.text()
      const preview = await repo.previewConfig({ text })
      applyImport(preview, { project: true, layers: true })
      setImported({ text, fileName: file.name, preview })
      // Already connected: check the config's paths against that repository - the one the
      // project uses, whatever repository the config names.
      if (testState === 'connected') {
        const want = preview.draft.branch
        const ref = want && branches.includes(want) ? want : branch
        if (ref !== branch) { setBranch(ref); void loadRepoTree(ref) }
        await checkImportAgainstRepo({ text, fileName: file.name, preview }, ref, true)
      }
    } catch (e) {
      toast.error('Could not read the config', (e as Error).message)
    } finally {
      setImportBusy(false)
    }
  }
  async function checkImportAgainstRepo(imp: { text: string; fileName: string; preview: ConfigPreview }, ref: string, layersToo: boolean) {
    // Restored from a draft, the import has no file text to send: its paths are checked by step 3.
    if (!imp.text) return
    const seq = ++checkSeq.current
    setImportChecking(true)
    try {
      const preview = await repo.previewConfig({
        text: imp.text, repo_url: repoUrl.trim(), branch: ref || undefined, access_token: token.trim() || undefined,
      })
      if (seq !== checkSeq.current) return                   // the user has moved on
      applyImport(preview, { project: false, layers: layersToo })
      // The architecture is the user's now: keep what the import said about it, take the rest.
      const report = layersToo ? preview.report : [
        ...imp.preview.report.filter((i) => i.topic === 'architecture'),
        ...preview.report.filter((i) => i.topic !== 'architecture'),
      ]
      setImported({ text: imp.text, fileName: imp.fileName, preview: { ...preview, report } })
    } catch (e) {
      if (seq === checkSeq.current) toast.error('Could not check the config against the repository', (e as Error).message)
    } finally {
      if (seq === checkSeq.current) setImportChecking(false)
    }
  }
  function applyImport(preview: ConfigPreview, opts: { project: boolean; layers: boolean }) {
    const d = preview.draft
    if (opts.project) {
      // A config fills the name and repository only when they are empty: what the user typed wins.
      const keptNow: string[] = []
      if (d.name && name.trim() !== d.name) {
        if (!name.trim()) setName(d.name)
        else keptNow.push('project name')
      }
      if (d.repoUrl && repoUrl.trim() !== d.repoUrl) {
        if (!repoUrl.trim()) { setRepoUrl(d.repoUrl); repoChanged() }
        else keptNow.push('repository')
      }
      setImportKept(keptNow)
      setPreferredBranch(d.branch ?? '')
      // The config's cores replace the wizard's: its layers name them. Their files are the user's
      // own, never the repository's, so a re-check against a branch leaves the cores alone.
      updateCores(() => draftToCores(d.cores, uid))
      setFolderResult(null)
    }
    if (opts.layers) {
      const next = draftToLayers(d.layers, uid, coresRef.current)
      setLayers(next)
      setFileAssignments(assignmentsOf(next))
      markArchEdited(false)
    }
  }

  /* ── Step 2 helpers — cores; their files upload to /repositories/uploads ── */
  const patchCore = (id: string, patch: Partial<Core>) =>
    updateCores((cs) => cs.map((c) => (c.id === id ? { ...c, ...patch } : c)))
  function addCore() {
    const c = newCore(uid(), nextCoreName(coresRef.current))
    updateCores((cs) => [...cs, c])
  }
  function removeCore(id: string) {
    updateCores((cs) => cs.filter((c) => c.id !== id))
    if (layers.some((l) => l.coreId === id)) {
      markArchEdited()
      setLayers((prev) => prev.map((l) => (l.coreId === id ? { ...l, coreId: null } : l)))
    }
  }
  // Uploads `f` once and gives it to every one of `slots` (all of one kind); how many it filled.
  async function uploadCoreFile(slots: { coreId: string; slot: CoreFile }[], f: File): Promise<number> {
    const spec = CORE_FILES[slots[0].slot]
    if (!fitsCoreFile(slots[0].slot, f.name)) {
      toast.error('This file cannot be used', `${f.name}: ${spec.need}.`)
      return 0
    }
    const keys = slots.map((s) => `${s.coreId}:${s.slot}`)
    setUploading((p) => new Set([...p, ...keys]))
    try {
      const u = await repo.upload(f, spec.kind)
      for (const s of slots) patchCore(s.coreId, { [s.slot]: { fileId: u.id, fileName: u.fileName, size: u.size } })
      return slots.length
    } catch (e) {
      toast.error('Upload failed', `${f.name}: ${(e as Error).message}`)
      return 0
    } finally {
      setUploading((p) => new Set([...p].filter((k) => !keys.includes(k))))
    }
  }
  // The paths an imported config names for a core's files (by the core's name in the config, so
  // a rename keeps them).
  const wantedFor = (c: Core) => (c.from ? imported?.preview.expectedUploads[c.from] : undefined)
  const openFiles = cores.flatMap((c) => openWants(c, wantedFor(c)))
  // A picked folder fills every file the config names that it holds (helpers.matchFolder); only
  // those are uploaded, each once however many cores share it.
  async function fillFromFolder(files: File[]) {
    const picked = files.map((file) => ({ path: file.webkitRelativePath || file.name, file }))
    const m = matchFolder(coresRef.current.flatMap((c) => openWants(c, wantedFor(c))), picked)
    const uploads = new Map<string, { file: File; slots: WantedFile[] }>()
    for (const { want, file } of m.found) {
      const key = `${file.path}|${want.slot}`
      uploads.set(key, { file: file.file, slots: [...(uploads.get(key)?.slots ?? []), want] })
    }
    const label = (w: WantedFile) => `${coresRef.current.find((c) => c.id === w.coreId)?.name.trim() ?? '?'}: ${baseName(w.path)}`
    setFolderBusy(true)
    try {
      const added = (await Promise.all([...uploads.values()].map((u) => uploadCoreFile(u.slots, u.file))))
        .reduce((a, n) => a + n, 0)
      setFolderResult({ folder: picked[0].path.split('/')[0], added, missing: m.missing.map(label), unsure: m.unsure.map(label) })
    } finally {
      setFolderBusy(false)
    }
  }
  const coreName = (id: string | null) => cores.find((c) => c.id === id)?.name.trim() || null

  /* ── Step 3 helpers ── */
  function openAddLayer() {
    setNewLayerCore(cores[0]?.id ?? '')
    setAddLayerOpen(true)
  }
  function confirmAddLayer() {
    const nm = newLayerName.trim().toUpperCase().replace(/\s+/g, '_')
    if (!nm) return
    markArchEdited()
    const coreId = cores.some((c) => c.id === newLayerCore) ? newLayerCore : null
    setLayers((prev) => [...prev, { id: uid(), name: nm, path: newLayerPath.trim(), groups: [], libPaths: [], coreId, collapsed: false }])
    setNewLayerName(''); setNewLayerPath(''); setAddLayerOpen(false)
  }
  const patchLayer = (id: string, fn: (l: Layer) => Layer) =>
    setLayers((prev) => prev.map((l) => (l.id === id ? fn(l) : l)))
  function confirmGroup() {
    const v = inlineVal.trim()
    if (!v || !inlineAdd) return
    markArchEdited()
    patchLayer(inlineAdd.parentId, (l) => ({ ...l, groups: [...l.groups, { id: uid(), name: v, comps: [], collapsed: false }] }))
    setInlineAdd(null); setInlineVal('')
  }
  function freeFiles(files: string[]) {
    setFileAssignments((prev) => { const next = { ...prev }; files.forEach((f) => delete next[f]); return next })
  }
  // One click removes a whole layer or group: keep what was there, so it can be undone.
  function keepForUndo(label: string) {
    setLastRemoved({ label, layers, assignments: fileAssignments })
  }
  function undoRemove() {
    if (!lastRemoved) return
    setLayers(lastRemoved.layers)
    setFileAssignments(lastRemoved.assignments)
    setLastRemoved(null)
  }
  function removeGroup(layerId: string, g: Group) {
    keepForUndo(`Removed group ${g.name} (${plural(g.comps.length, 'component')})`)
    markArchEdited()
    freeFiles(g.comps.flatMap((c) => c.files))
    patchLayer(layerId, (l) => ({ ...l, groups: l.groups.filter((x) => x.id !== g.id) }))
  }
  function removeLayer(layer: Layer) {
    keepForUndo(`Removed layer ${layer.name} (${plural(layer.groups.reduce((a, g) => a + g.comps.length, 0), 'component')})`)
    markArchEdited()
    freeFiles(layer.groups.flatMap((g) => g.comps.flatMap((c) => c.files)))
    setLayers((prev) => prev.filter((l) => l.id !== layer.id))
  }
  function removeComp(layerId: string, groupId: string, comp: Comp) {
    keepForUndo(`Removed component ${comp.name}`)
    markArchEdited()
    freeFiles(comp.files)
    patchLayer(layerId, (l) => ({ ...l, groups: l.groups.map((g) => (g.id === groupId ? { ...g, comps: g.comps.filter((c) => c.id !== comp.id) } : g)) }))
  }
  function toggleComp(layerId: string, groupId: string, compId: string) {
    patchLayer(layerId, (l) => ({ ...l, groups: l.groups.map((g) => (g.id === groupId ? { ...g, comps: g.comps.map((c) => (c.id === compId ? { ...c, collapsed: !c.collapsed } : c)) } : g)) }))
  }
  // Add-Component panel — the file tree is rooted at the layer's path.
  const layerRootLabel = (l?: Layer) => `${l?.path || l?.name || 'layer'}/`
  const subtreeFor = (path: string): RepoEntry[] => {
    const norm = (path || '').replace(/\/+$/, '')
    return norm ? (findNode(repoTree, norm)?.children ?? []) : repoTree
  }
  function openCompPanel(layerId: string, groupId: string) {
    const layer = layers.find((l) => l.id === layerId)
    setCompPanel({ layerId, groupId }); setCompName(''); setSelectedFiles(new Set())
    setTreeOpen({ [layer?.path || '__root__']: true })
  }
  function closeCompPanel() { setCompPanel(null); setCompName(''); setSelectedFiles(new Set()) }
  function toggleFile(f: string) {
    setSelectedFiles((prev) => { const next = new Set(prev); next.has(f) ? next.delete(f) : next.add(f); return next })
  }
  function toggleFolder(node: RepoEntry) {
    const files = descendantFiles(node).filter((f) => !ownerOf(f, fileAssignments))
    const allSel = files.length > 0 && files.every((f) => selectedFiles.has(f))
    setSelectedFiles((prev) => { const next = new Set(prev); files.forEach((f) => (allSel ? next.delete(f) : next.add(f))); return next })
    if (!allSel) setTreeOpen((prev) => ({ ...prev, [node.path]: true }))
  }
  function confirmAddComponent() {
    const nm = compName.trim()
    if (!nm || !compPanel) return
    markArchEdited()
    const files = [...selectedFiles]
    setFileAssignments((prev) => { const next = { ...prev }; files.forEach((f) => (next[f] = nm)); return next })
    patchLayer(compPanel.layerId, (l) => ({ ...l, groups: l.groups.map((g) => (g.id === compPanel.groupId ? { ...g, comps: [...g.comps, { id: uid(), name: nm, files, collapsed: false }] } : g)) }))
    closeCompPanel()
  }
  const panelLayer = compPanel ? layers.find((l) => l.id === compPanel.layerId) : undefined
  // Add-Component file tree, rooted at the selected layer's path (real repo tree).
  const compRoot = layerRootLabel(panelLayer)
  const compTree: RepoEntry[] = [{ type: 'folder', name: compRoot, path: panelLayer?.path || '__root__', children: panelLayer ? subtreeFor(panelLayer.path) : [] }]
  // Select-Folder picker — rooted at the Step-1 repo (folders only).
  const repoRoot = repoRootName(repoUrl)
  // Once per tree, not on every keystroke: it walks the whole branch.
  const repoFolders = useMemo(() => foldersOnly(repoTree), [repoTree])
  const pickerTree: RepoEntry[] = [{ type: 'folder', name: repoRoot, path: '.', children: repoFolders }]
  const fpDisplay = fpSelected ? (fpSelected === '.' ? repoRoot : `${repoRoot}/${fpSelected}`) : 'No folder selected'
  function openFolderPicker(target: FpTarget) {
    setFpTarget(target); setFpSelected('')
    // Expand the project root + its first level by default.
    setFpOpen({ '.': true, ...Object.fromEntries(repoFolders.map((n) => [n.path, true])) })
  }
  function confirmFolderPicker() {
    if (!fpSelected || !fpTarget) return
    if (fpTarget.kind === 'lib-path') markArchEdited()
    if (fpTarget.kind === 'new-layer-path') setNewLayerPath(fpSelected)
    else patchLayer(fpTarget.layerId, (l) => ({ ...l, libPaths: l.libPaths.map((x, i) => (i === fpTarget.index ? fpSelected : x)) }))
    setFpTarget(null)
  }
  const totalComps = layers.reduce((a, l) => a + l.groups.reduce((b, g) => b + g.comps.length, 0), 0)
  // Every path of the project against the selected branch (helpers.pathProblems). A run reads
  // exactly these paths: one that is not there was skipped without a word, and a component left
  // with no file stopped the run after the whole parse. So the project is created only when
  // there are none.
  const treeIndex = useMemo(() => indexTree(repoTree), [repoTree])
  const problems = useMemo(() => pathProblems(layers, treeIndex, branch), [layers, treeIndex, branch])
  const treeReady = !!branch && !repoTreeLoading && !repoTreeFailed && repoTreeFor === branch
  const issueAt = useMemo(() => {
    const m = new Map<string, string>()
    for (const pr of problems) m.set(`${pr.layerId}|${pr.compId ?? ''}|${pr.path}`, pr.text)
    return m
  }, [problems])
  const layerIssueCount = (layerId: string) =>
    treeReady ? problems.filter((pr) => pr.layerId === layerId).length : 0
  const compIssue = (layerId: string, compId: string) =>
    treeReady ? problems.filter((pr) => pr.layerId === layerId && pr.compId === compId).map((pr) => pr.text).join('\n') : ''
  const pathIssue = (layerId: string, compId: string, path: string) =>
    treeReady ? issueAt.get(`${layerId}|${compId}|${path}`) : undefined

  /* ── Step 4 helpers ── */
  const takenEmails = [me.email, ...members.map((m) => m.email)]
  function selectMember(email: string, mname?: string) {
    if (members.some((m) => m.email === email)) return
    setMembers((prev) => [...prev, { name: mname, email, role: inviteRole }])
    closeAddMember()
  }
  function closeAddMember() {
    setAddMemberOpen(false); setSearch(''); setSearchOpen(false); setInviteRole('Developer'); setSearchResults([])
  }
  // Debounced org-directory search against GET /users/search.
  useEffect(() => {
    if (!addMemberOpen) return
    let active = true
    setSearchLoading(true)
    const t = window.setTimeout(async () => {
      try {
        const users = await repo.searchUsers(search.trim())
        if (active) setSearchResults(users)
      } catch {
        if (active) setSearchResults([])
      } finally {
        if (active) setSearchLoading(false)
      }
    }, 200)
    return () => { active = false; window.clearTimeout(t) }
  }, [search, addMemberOpen, repo])
  const searchMatches = searchResults.filter((u) => !takenEmails.includes(u.email))

  /* ── Navigation ── */
  // What stops each step, worked out live. It shows inside the step once Continue was tried there
  // (not in a toast that is gone before it is read), and marks the step in the rail.
  function issuesFor(n: number): string[] {
    if (n === 1) {
      return [
        !name.trim() && 'Give the project a name',
        !repoUrl.trim() && 'Enter the repository URL',
        !!repoUrl.trim() && testState !== 'connected' && 'Test the connection to load the branches',
        testState === 'connected' && !branch && 'Pick a branch',
      ].filter((t): t is string => !!t)
    }
    if (n === 2) return uploading.size ? ['Core files are still uploading - wait for them to finish'] : coreProblems(cores)
    if (n === 3) {
      if (repoTreeLoading) return []                     // the step says it is reading the branch
      if (!treeReady) return ["The repository's files could not be read - test the connection again in step 1"]
      return problems.map((p) => p.text)
    }
    return []
  }
  const railIssues = new Set([1, 2, 3].filter((n) => (attempted.has(n) || done.has(n)) && issuesFor(n).length > 0))
  function validate(n: number): boolean {
    if (n === 1) {
      setErrs({ name: !name.trim(), repo: !repoUrl.trim(), branch: testState === 'connected' && !branch })
      if (repoUrl.trim() && testState !== 'connected') setTestMsg({ text: 'Test the connection first to load branches.', tone: 'error' })
    }
    if ((n === 3 || n === 5) && repoTreeLoading) {
      toast.info('Still reading the repository', `Checking the paths against branch ${branch}. Try again in a moment.`)
      return false
    }
    // The last step re-checks every step before it and takes the user to the first that needs a fix.
    const bad = (n === STEPS.length ? [1, 2, 3] : [n]).find((k) => issuesFor(k).length > 0)
    if (bad === undefined) return true
    setAttempted((p) => new Set(p).add(bad))
    if (bad !== cur) setCur(bad)
    scrollRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    return false
  }
  function back() { if (cur > 1) setCur(cur - 1) }
  function cont() {
    if (!validate(cur)) return
    if (cur < STEPS.length) {
      setDone((prev) => new Set(prev).add(cur))
      setCur(cur + 1)
    } else {
      onSubmit({
        name: name.trim(),
        client: '',
        compliance_standard: 'ISO_26262',
        repo_url: repoUrl.trim(),
        repo_provider: 'github',
        default_branch: branch || undefined,
        access_token: token.trim() || undefined,
        build_config: {
          ...(imported?.preview.draft.settings ?? {}),
          cores: cores.map(coreInput),
        },
        architecture_layers: layers.map((l) => ({
          name: l.name,
          path: l.path,
          core: coreName(l.coreId),
          lib_paths: l.libPaths.map((p) => p.trim()).filter(Boolean),
          groups: l.groups.map((g) => ({
            name: g.name,
            components: g.comps.map((c) => ({ name: c.name, files: c.files })),
          })),
        })),
        // Server adds each selected developer as an active project member.
        team: members.map((m) => ({ email: m.email, role: m.role.toLowerCase() })),
      })
    }
  }
  function railGo(n: number) { if (n < cur || done.has(n)) setCur(n) }

  /* ── Step 5: is the project ready? `error` blocks creating it; `warn` is what it would miss. ── */
  const readiness: ReadinessItem[] = (() => {
    const out: ReadinessItem[] = []
    const s1 = issuesFor(1)
    out.push(s1.length ? { state: 'error', title: 'Project and repository', detail: s1.join(' · '), fix: 1 }
      : { state: 'ok', title: `Repository connected · branch ${branch}` })
    const s3 = issuesFor(3)
    out.push(repoTreeLoading ? { state: 'warn', title: `Still reading branch ${branch} to check every path` }
      : s3.length ? { state: 'error', title: `${plural(s3.length, 'thing')} to fix in the architecture`,
        detail: s3[0] + (s3.length > 1 ? ` (and ${s3.length - 1} more)` : ''), fix: 3 }
        : { state: 'ok', title: `Every path is on branch ${branch} · ${plural(layers.length, 'layer')}, ${plural(totalComps, 'component')}` })
    const s2 = issuesFor(2)
    out.push(s2.length ? { state: 'error', title: 'Cores', detail: s2.join(' · '), fix: 2 }
      : cores.length ? { state: 'ok', title: `${plural(cores.length, 'core')}: ${cores.map((c) => c.name.trim()).join(', ')}` }
        : { state: 'warn', title: 'No cores', detail: 'Every layer is parsed without macros or a data dictionary.', fix: 2 })
    // Files an imported config names that were never uploaded, per core.
    const pending = cores.map((c) => ({ core: c, files: openWants(c, wantedFor(c)).map((w) => baseName(w.path)) }))
      .filter((x) => x.files.length)
    if (pending.length) {
      const n = pending.reduce((a, x) => a + x.files.length, 0)
      out.push({ state: 'warn', title: `${plural(n, 'file')} the config names ${n === 1 ? 'is' : 'are'} not uploaded`,
        detail: pending.map((x) => `${x.core.name.trim()}: ${x.files.join(', ')}`).join(' · '), fix: 2 })
    }
    const noMacros = cores.filter((c) => !pending.some((x) => x.core.id === c.id)
      && !(c.macroMode === 'typed' ? typedDefines(c.macroText).length : c.macroFile)).map((c) => c.name.trim())
    if (noMacros.length) {
      out.push({ state: 'warn', title: `${noMacros.join(', ')}: no macros`,
        detail: 'Its layers parse without their -D flags, so #if branches may be read the wrong way.', fix: 2 })
    }
    const noCore = cores.length ? layers.filter((l) => !cores.some((c) => c.id === l.coreId)).map((l) => l.name) : []
    if (noCore.length) {
      out.push({ state: 'warn', title: `${noCore.join(', ')}: no core`, detail: 'Parsed without macros or a data dictionary.', fix: 3 })
    }
    out.push({ state: 'ok', title: members.length ? `You and ${plural(members.length, 'member')}` : 'Just you - people can be added later from Team' })
    return out
  })()
  const isLast = cur === STEPS.length
  const testMsgCls = testMsg?.tone === 'error' ? 'text-error' : testMsg?.tone === 'ok' ? 'text-[#00a572]' : 'text-on-surface-variant'

  return (
    <div className="flex-1 overflow-hidden flex">
      <StepRail cur={cur} done={done} issues={railIssues} onClose={onCancel} onGo={railGo} />

      {/* Form area */}
      <div className="flex-1 flex flex-col overflow-hidden bg-background">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="max-w-2xl mx-auto px-6 py-6 space-y-5">
            <StepHeader title={STEP_HEADERS[cur - 1].title} sub={STEP_HEADERS[cur - 1].sub} />
            {/* Step 3 lists its own path problems, marked on the tree. */}
            {attempted.has(cur) && cur !== 3 && <StepIssues items={issuesFor(cur)} />}

            {/* ══ STEP 1 — PROJECT & REPOSITORY ══ */}
            {/* Config import comes first: it fills the fields below it (name, repository, branch), and
                everything after. Test Connection and a branch change check its paths against the branch. */}
            {cur === 1 && (
              <ConfigImport fileName={imported?.fileName} preview={imported?.preview} busy={importBusy} onPick={(f) => { void importConfig(f) }} archChanged={archChanged} branch={branch} kept={importKept}
                checking={importChecking || (!!imported && !imported.preview.repositoryChecked && (testState === 'connecting' || repoTreeLoading))} />
            )}
            {cur === 1 && (
              <div className="card space-y-4">
                <div>
                  <div className="lbl">Project Name <span className="req">*</span></div>
                  <input className={`inp ${errs.name ? 'err' : ''}`} value={name} onChange={(e) => { setName(e.target.value); setErrs((p) => ({ ...p, name: false })) }} type="text" placeholder="e.g. VCU Engine Firmware" />
                </div>

                <div>
                  <div className="lbl">Repository URL <span className="req">*</span></div>
                  <input className={`inp mono ${errs.repo ? 'err' : ''}`} value={repoUrl} onChange={(e) => { setRepoUrl(e.target.value); setErrs((p) => ({ ...p, repo: false })); repoChanged() }} type="text" placeholder="https://github.com/org/repo.git" />
                </div>

                {/* Only a private repository needs a token: out of the way until asked for. */}
                {tokenOpen || token ? (
                  <div>
                    <div className="lbl">
                      Access Token
                      <span className="ml-auto text-on-surface-variant font-mono text-caption font-normal tracking-normal normal-case">Optional — for private repos</span>
                    </div>
                    <div className="relative">
                      <input autoFocus={!token} className="inp mono pr-10" value={token} onChange={(e) => { setToken(e.target.value); repoChanged() }} type={showToken ? 'text' : 'password'} placeholder="ghp_xxxxxxxxxxxxxxxxxxxx" />
                      <button type="button" onClick={() => setShowToken((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors">
                        <Icon name={showToken ? 'visibility' : 'visibility_off'} size={17} />
                      </button>
                    </div>
                  </div>
                ) : (
                  <button type="button" onClick={() => setTokenOpen(true)} className="group -mt-1 flex items-center gap-1 text-caption text-secondary">
                    <Icon name="lock" size={13} /><span className="group-hover:underline">Private repository? Add an access token</span>
                  </button>
                )}

                {/* Test connection */}
                <div className="flex items-center gap-3 pt-1">
                  <button onClick={testConnection} disabled={testState === 'connecting'} className="flex items-center gap-1.5 px-4 py-2 border border-outline-variant rounded-lg bg-surface-container-low hover:bg-surface-container transition-colors flex-shrink-0 disabled:opacity-60 font-mono text-caption font-bold tracking-[.06em] uppercase text-on-surface-variant">
                    <Icon name="wifi_tethering" size={15} />
                    Test Connection
                  </button>
                  {testMsg && (
                    <span className={cn('flex items-center text-xs', testMsgCls)}>
                      {testMsg.tone === 'ok' && <Icon name="check_circle" size={14} fill className="mr-[3px]" />}
                      {testMsg.text}
                    </span>
                  )}
                </div>

                {/* Branch — revealed after a successful test */}
                {testState === 'connected' && (
                  <div>
                    <div className="h-px bg-surface-container-low mb-4" />
                    <div className="lbl">Branch <span className="req">*</span></div>
                    {branches.length > 10 && (
                      <>
                        <input className="inp mb-1.5" type="search" placeholder="Search branches…" value={branchQuery}
                          onChange={(e) => setBranchQuery(e.target.value)} aria-label="Search branches" />
                        {branchQuery.trim() && (
                          <div className="text-on-surface-variant font-mono text-caption mb-1.5">
                            {shownBranches.length} of {branches.length} branches
                          </div>
                        )}
                      </>
                    )}
                    <select className={`inp ${errs.branch ? 'err' : ''}`} value={branch} onChange={(e) => {
                      const b = e.target.value; setBranch(b); setErrs((p) => ({ ...p, branch: false }))
                      if (b) {
                        // Paths differ between branches: check an imported config against this one -
                        // after the tree, which fetches the branch; the check then reuses it.
                        void (async () => {
                          await loadRepoTree(b)
                          if (imported) await checkImportAgainstRepo(imported, b, !archEdited.current)
                        })()
                      }
                    }}>
                      <option value="">Select a branch…</option>
                      {shownBranches.map((b) => <option key={b} value={b}>{b}</option>)}
                    </select>
                  </div>
                )}
              </div>
            )}
            {/* ══ STEP 2 — CORES ══ */}
            {cur === 2 && (
              <CoresStep cores={cores} layers={layers} wanted={wantedFor} uploading={uploading}
                openFiles={openFiles.length} folder={folderResult} folderBusy={folderBusy}
                onAdd={addCore} onRemove={removeCore} onChange={patchCore}
                onPick={(id, slot, f) => { void uploadCoreFile([{ coreId: id, slot }], f) }}
                onFolder={(fs) => { void fillFromFolder(fs) }} />
            )}

            {/* ══ STEP 3 — ARCHITECTURE ══ */}
            {cur === 3 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Icon name="account_tree" size={17} className="text-secondary" />
                    <span className="text-on-surface-variant uppercase font-mono text-xs font-medium tracking-[.08em]">Project Architecture</span>
                  </div>
                  <button onClick={openAddLayer} className="flex items-center gap-1.5 px-3 py-1.5 text-secondary border border-outline-variant rounded-lg hover:bg-surface-container-low transition-colors font-mono text-xs font-medium">
                    <Icon name="add" size={15} /> Add Layer
                  </button>
                </div>

                {repoTreeLoading ? (
                  <p className="flex items-center gap-2 font-mono text-caption text-on-surface-variant">
                    <Icon name="progress_activity" size={14} className="animate-spin" />
                    Reading branch {branch} to check every path…
                  </p>
                ) : !treeReady ? (
                  <div className="flex items-start gap-2 p-3 bg-error-container border border-error rounded-xl text-xs text-on-error-container">
                    <Icon name="error" size={15} fill className="flex-shrink-0 mt-px text-error" />
                    <span>The repository&apos;s files could not be read, so no path can be checked. Test the connection again in step 1.</span>
                  </div>
                ) : problems.length > 0 ? (
                  <div className="p-3.5 bg-error-container border border-error rounded-xl">
                    <p className="flex items-center gap-2 font-mono text-xs font-semibold text-on-error-container">
                      <Icon name="error" size={15} fill className="text-error" />
                      {problems.length === 1 ? 'One thing' : `${problems.length} things`} to fix before the project is created
                    </p>
                    <ul className="mt-2 ml-6 space-y-1 list-disc">
                      {problems.slice(0, 8).map((pr, i) => (
                        <li key={i} className="text-xs text-on-error-container leading-[1.45]"><CodeText text={pr.text} /></li>
                      ))}
                    </ul>
                    {problems.length > 8 && <p className="mt-1.5 ml-6 text-xs text-on-error-container">…and {problems.length - 8} more, marked below.</p>}
                  </div>
                ) : (
                  <p className="flex items-center gap-2 font-mono text-caption text-[#00a572]">
                    <Icon name="check_circle" size={14} fill />
                    Every path is on branch {branch}.
                  </p>
                )}

                <div className="space-y-2">
                  {layers.length === 0 && !addLayerOpen && (
                    <div className="flex flex-col items-center justify-center py-10 text-center">
                      <Icon name="account_tree" size={36} className="text-on-surface-variant mb-3 opacity-35" />
                      <p className="text-on-surface-variant font-mono text-xs font-medium">No layers yet.</p>
                      <p className="text-on-surface-variant mt-1 text-xs">Click <strong>Add Layer</strong> to start mapping your architecture.</p>
                    </div>
                  )}

                  {layers.map((layer) => (
                    <div key={layer.id} className="layer-block">
                      <div className="layer-head" onClick={() => patchLayer(layer.id, (l) => ({ ...l, collapsed: !l.collapsed }))}>
                        <Icon name={layer.collapsed ? 'keyboard_arrow_right' : 'keyboard_arrow_down'} size={15} className="text-on-surface-variant" />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-on-surface font-mono text-body font-bold leading-[1.3]">{layer.name}</span>
                            {layerIssueCount(layer.id) > 0 && (
                              <span className="px-1.5 rounded bg-error-container text-error font-mono text-micro font-bold">{layerIssueCount(layer.id)} to fix</span>
                            )}
                          </div>
                          {/* Root folder, then what the layer holds - enough to leave it collapsed. */}
                          <span className={cn(`layer-path-display ${layer.path ? '' : 'empty'}`, pathIssue(layer.id, '', layer.path) && 'err')} title={pathIssue(layer.id, '', layer.path)?.replace(/`/g, '')}>
                            {layer.path ? `${layer.path}/` : 'Set root path…'}
                            <span className="text-outline">{` · ${plural(layer.groups.length, 'group')} · ${plural(layer.groups.reduce((a, g) => a + g.comps.length, 0), 'component')}`}</span>
                          </span>
                        </div>
                        <label className="layer-core" onClick={(e) => e.stopPropagation()} title="The core this layer is built for: its macros, data dictionary and compile commands">
                          Core
                          <select className="layer-core-select" value={layer.coreId ?? ''} onChange={(e) => { markArchEdited(); patchLayer(layer.id, (l) => ({ ...l, coreId: e.target.value || null })) }}>
                            <option value="">No core</option>
                            {cores.map((c) => <option key={c.id} value={c.id}>{c.name.trim() || 'Unnamed core'}</option>)}
                          </select>
                        </label>
                        <button onClick={(e) => { e.stopPropagation(); removeLayer(layer) }} className="p-1 text-on-surface-variant hover:text-error transition-colors">
                          <Icon name="close" size={15} />
                        </button>
                      </div>

                      {!layer.collapsed && (
                        <div className="layer-body">
                          {/* Groups */}
                          {layer.groups.map((g) => (
                            <div key={g.id}>
                              <div className="tree-group-row">
                                <button onClick={() => patchLayer(layer.id, (l) => ({ ...l, groups: l.groups.map((x) => x.id === g.id ? { ...x, collapsed: !x.collapsed } : x) }))} className="tree-toggle">
                                  <Icon name={g.collapsed ? 'keyboard_arrow_right' : 'keyboard_arrow_down'} size={14} />
                                </button>
                                <Icon name={g.collapsed ? 'folder' : 'folder_open'} size={14} className="text-secondary" />
                                <span className="text-on-surface flex-1 font-mono text-body">{g.name}</span>
                                <button onClick={() => removeGroup(layer.id, g)} className="p-1 text-on-surface-variant hover:text-error transition-colors">
                                  <Icon name="close" size={14} />
                                </button>
                              </div>
                              {!g.collapsed && (
                                <div className="tree-children">
                                  {g.comps.map((c) => (
                                    <div key={c.id}>
                                      <div className="tree-comp-row">
                                        <button onClick={() => toggleComp(layer.id, g.id, c.id)} className="tree-toggle">
                                          <Icon name={c.files.length > 0 && !c.collapsed ? 'keyboard_arrow_down' : 'keyboard_arrow_right'} size={13} />
                                        </button>
                                        <Icon name="folder" size={13} className="text-secondary opacity-60" />
                                        <span className="text-on-surface flex-1 font-mono text-body">{c.name}</span>
                                        {compIssue(layer.id, c.id) && (
                                          <span title={compIssue(layer.id, c.id).replace(/`/g, '')} className="flex items-center text-error">
                                            <Icon name="error" size={14} fill />
                                          </span>
                                        )}
                                        <button onClick={() => removeComp(layer.id, g.id, c)} className="p-1 text-on-surface-variant hover:text-error transition-colors">
                                          <Icon name="close" size={13} />
                                        </button>
                                      </div>
                                      {c.files.length > 0 && !c.collapsed && (
                                        <div className="comp-files">
                                          {c.files.map((f) => {
                                            const issue = pathIssue(layer.id, c.id, f)
                                            return (
                                              <div key={f} className={cn('file-row', issue && 'err')} title={issue?.replace(/`/g, '') ?? f}>
                                                <Icon name={treeIndex.get(f) === 'folder' ? 'folder' : 'description'} size={12} className={issue ? 'text-error' : 'text-[#b0b3b8]'} />{f.split('/').pop()}
                                                {issue && <span className="ml-1.5 font-mono text-micro">not usable</span>}
                                              </div>
                                            )
                                          })}
                                        </div>
                                      )}
                                    </div>
                                  ))}
                                  <button onClick={() => openCompPanel(layer.id, g.id)} className="add-group-btn pl-5">
                                    <Icon name="add" size={12} /> Add Component
                                  </button>
                                </div>
                              )}
                            </div>
                          ))}

                          {/* Add group */}
                          {inlineAdd?.parentId === layer.id ? (
                            <div className="inline-add-row">
                              <input autoFocus className="inline-add-input" value={inlineVal} onChange={(e) => setInlineVal(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') confirmGroup(); if (e.key === 'Escape') { setInlineAdd(null); setInlineVal('') } }} placeholder="Group name…" />
                              <button className="inline-add-confirm" onClick={confirmGroup}>Add</button>
                              <button className="inline-add-cancel" onClick={() => { setInlineAdd(null); setInlineVal('') }}><Icon name="close" size={14} /></button>
                            </div>
                          ) : (
                            <button onClick={() => { setInlineAdd({ parentId: layer.id }); setInlineVal('') }} className="add-group-btn">
                              <Icon name="add" size={12} /> Add Group
                            </button>
                          )}

                          {/* Lib paths - optional: a link until the layer has one */}
                          {layer.libPaths.length === 0 ? (
                            <button onClick={() => { markArchEdited(); patchLayer(layer.id, (l) => ({ ...l, libPaths: [''] })) }} className="add-group-btn text-outline" title="External include paths (-I flags) for this layer.">
                              <Icon name="add" size={12} /> Lib path <span className="font-normal">(optional)</span>
                            </button>
                          ) : (
                          <div className="inc-paths-section">
                            <div className="inc-paths-row">
                              <div className="inc-paths-label" title="External include paths (-I flags) for this layer.">Lib Paths</div>
                              <div className="inc-paths-content">
                                {layer.libPaths.map((p, idx) => (
                                  <div key={idx} className="ext-path-row">
                                    <Icon name="folder_open" size={13} className="text-[#00a572] flex-shrink-0" />
                                    <input className={cn('ext-path-input', pathIssue(layer.id, '', p) && 'err')} title={pathIssue(layer.id, '', p)?.replace(/`/g, '')} value={p} placeholder="/path/to/include" onChange={(e) => { markArchEdited(); patchLayer(layer.id, (l) => ({ ...l, libPaths: l.libPaths.map((x, i) => i === idx ? e.target.value : x) })) }} />
                                    <button type="button" className="ext-browse-btn" onClick={() => openFolderPicker({ kind: 'lib-path', layerId: layer.id, index: idx })}>
                                      <Icon name="folder_open" size={11} />BROWSE
                                    </button>
                                    <button onClick={() => { markArchEdited(); patchLayer(layer.id, (l) => ({ ...l, libPaths: l.libPaths.filter((_, i) => i !== idx) })) }} className="flex items-center bg-transparent border-none cursor-pointer p-0 text-outline">
                                      <Icon name="close" size={13} className="leading-none" />
                                    </button>
                                  </div>
                                ))}
                                <button onClick={() => { markArchEdited(); patchLayer(layer.id, (l) => ({ ...l, libPaths: [...l.libPaths, ''] })) }} className="inc-add-btn">
                                  <Icon name="add" size={12} className="align-middle" /> Add path
                                </button>
                              </div>
                            </div>
                          </div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>

                {lastRemoved && (
                  <div role="status" className="sticky bottom-3 z-10 flex items-center gap-3 px-4 py-2.5 bg-primary text-white rounded-lg shadow-[0_4px_16px_rgba(4,22,39,.25)]">
                    <Icon name="delete" size={16} className="opacity-70" />
                    <span className="flex-1 text-xs">{lastRemoved.label}</span>
                    <button type="button" onClick={undoRemove} className="font-mono text-caption font-bold uppercase tracking-[.06em] text-[#8ab4ff] hover:text-white">Undo</button>
                    <button type="button" onClick={() => setLastRemoved(null)} aria-label="Dismiss" className="opacity-70 hover:opacity-100"><Icon name="close" size={15} /></button>
                  </div>
                )}

                {/* Add layer inline form */}
                {addLayerOpen && (
                  <div className="p-4 bg-surface-container-low border-2 border-dashed border-secondary rounded-xl space-y-3">
                    <div>
                      <div className="lbl mb-1">Layer Name</div>
                      <input autoFocus className="inp mono uppercase" value={newLayerName} onChange={(e) => setNewLayerName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') confirmAddLayer() }} type="text" placeholder="E.G. MIDDLEWARE_LAYER" />
                    </div>
                    <div>
                      <div className="lbl mb-1">Layer Root Path</div>
                      <div className="flex gap-2">
                        <input className="inp mono flex-1" value={newLayerPath} onChange={(e) => setNewLayerPath(e.target.value)} type="text" placeholder="Select a folder under the project root…" />
                        <button type="button" onClick={() => openFolderPicker({ kind: 'new-layer-path' })} className="flex items-center gap-1.5 px-3 border border-outline-variant rounded-lg hover:bg-surface-container transition-colors text-on-surface-variant flex-shrink-0 whitespace-nowrap font-mono text-caption font-bold tracking-[.04em]">
                          <Icon name="folder_open" size={16} /> Select Folder
                        </button>
                      </div>
                    </div>
                    <div>
                      <div className="lbl mb-1">Core</div>
                      <select className="inp mono" value={newLayerCore} onChange={(e) => setNewLayerCore(e.target.value)}>
                        <option value="">No core</option>
                        {cores.map((c) => <option key={c.id} value={c.id}>{c.name.trim() || 'Unnamed core'}</option>)}
                      </select>
                    </div>
                    <div className="flex gap-2 pt-1">
                      <button onClick={confirmAddLayer} className="px-4 py-2 bg-secondary text-on-secondary rounded-lg hover:bg-secondary-container transition-colors font-mono text-xs font-medium">Add Layer</button>
                      <button onClick={() => { setAddLayerOpen(false); setNewLayerName(''); setNewLayerPath('') }} className="px-4 py-2 border border-outline-variant text-on-surface-variant rounded-lg hover:bg-surface-container transition-colors font-mono text-xs font-medium">Cancel</button>
                    </div>
                  </div>
                )}

                <div className="flex items-start gap-3 p-3.5 bg-surface-container-low border border-outline-variant rounded-xl">
                  <Icon name="info" size={18} className="text-secondary flex-shrink-0" />
                  <p className="text-on-surface-variant text-xs">Layer root path is scanned by Clang. Groups define logical modules. Components map to physical source folders.</p>
                </div>
              </div>
            )}

            {/* ══ STEP 4 — TEAM ══ */}
            {cur === 4 && (
              <div className="space-y-4">
                <div className="card">
                  {/* Header row */}
                  <div className="flex items-center gap-3 pb-3 mb-1 border-b border-outline-variant font-mono text-label font-bold tracking-[.08em] uppercase text-outline">
                    <div className="w-7 flex-shrink-0" />
                    <span className="flex-1">Member</span>
                    <span className="w-[120px] flex-shrink-0">Role</span>
                    <span className="w-6 flex-shrink-0" />
                  </div>

                  {/* Self (pinned) */}
                  <div className="flex items-center gap-3 py-2.5">
                    <div className="w-7 h-7 rounded-full bg-primary-container flex items-center justify-center flex-shrink-0">
                      <span className="font-bold text-on-primary-container font-sans text-caption">{me.initials}</span>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-on-surface font-mono text-xs">{me.name} <span className="text-on-surface-variant font-normal">(you)</span></p>
                      <p className="text-on-surface-variant font-mono text-label">{me.email}</p>
                    </div>
                    <div className="w-[120px] flex-shrink-0">
                      <span className="inline-block font-mono text-micro font-bold tracking-[.06em] uppercase px-2 py-[3px] bg-primary-container text-on-primary-container rounded-[3px]">Admin</span>
                    </div>
                    <div className="w-6 flex-shrink-0" />
                  </div>

                  {/* Dynamic members */}
                  {members.map((m) => {
                    const isAdmin = m.role === 'Admin'
                    return (
                      <div key={m.email} className="flex items-center gap-3 py-2.5 border-t border-outline-variant">
                        <div className={cn('w-7 h-7 rounded-full flex items-center justify-center flex-shrink-0', isAdmin ? 'bg-primary-container' : 'bg-surface-container')}>
                          <span className={cn('font-sans text-caption font-bold', isAdmin ? 'text-on-primary-container' : 'text-secondary')}>{memberInitials(m)}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-on-surface truncate font-mono text-xs">{m.name || m.email}</p>
                          <p className="text-on-surface-variant truncate font-mono text-label">{m.email}</p>
                        </div>
                        <div className="w-[120px] flex-shrink-0">
                          <select value={m.role} onChange={(e) => setMembers((prev) => prev.map((x) => x.email === m.email ? { ...x, role: e.target.value as Role } : x))} className="font-mono text-label font-semibold tracking-[.04em] px-1.5 py-[3px] border border-outline-variant rounded-lg bg-white text-on-surface outline-none w-full">
                            <option value="Developer">Developer</option>
                            <option value="Admin">Admin</option>
                          </select>
                        </div>
                        <div className="w-6 flex-shrink-0">
                          <button onClick={() => setMembers((prev) => prev.filter((x) => x.email !== m.email))} className="text-on-surface-variant hover:text-error transition-colors">
                            <Icon name="close" size={16} />
                          </button>
                        </div>
                      </div>
                    )
                  })}

                  {/* Add row */}
                  <div className="pt-3 mt-1 border-t border-outline-variant">
                    {!addMemberOpen ? (
                      <button onClick={() => setAddMemberOpen(true)} className="flex items-center gap-2 text-secondary hover:text-secondary-container transition-colors font-mono text-caption font-bold tracking-[.04em] uppercase">
                        <Icon name="person_add" size={16} />
                        Add member
                      </button>
                    ) : (
                      <div className="space-y-3">
                        <div className="relative">
                          <div className="flex gap-2">
                            <div className="relative flex-1">
                              <Icon name="search" size={16} className="absolute left-[9px] top-1/2 -translate-y-1/2 text-outline pointer-events-none" />
                              <input className="inp with-icon" value={search} onChange={(e) => setSearch(e.target.value)} onFocus={() => setSearchOpen(true)} onBlur={() => window.setTimeout(() => setSearchOpen(false), 150)} type="text" autoComplete="off" placeholder="Search by name or email…" />
                            </div>
                            <select className="w-[120px] flex-shrink-0 px-2 border border-outline-variant rounded-lg bg-white text-on-surface outline-none font-mono text-label font-semibold tracking-[.04em]" value={inviteRole} onChange={(e) => setInviteRole(e.target.value as Role)}>
                              <option value="Developer">Developer</option>
                              <option value="Admin">Admin</option>
                            </select>
                          </div>
                          {searchOpen && (
                            <div className="absolute top-[calc(100%+4px)] left-0 right-[128px] bg-white border border-outline-variant rounded-lg shadow-[0_4px_16px_rgba(4,22,39,.12)] max-h-[200px] overflow-y-auto z-[200]">
                              {searchMatches.map((u) => (
                                <div key={u.email} className="ms-item" onMouseDown={() => selectMember(u.email, u.name)}>
                                  <div className="w-6 h-6 rounded-full bg-surface-container flex items-center justify-center flex-shrink-0 font-sans text-label font-bold text-secondary">{initialsOf(u.name)}</div>
                                  <div className="flex-1 min-w-0">
                                    <p className="text-body text-on-surface leading-[1.3]">{u.name}</p>
                                    <p className="text-caption text-outline font-mono">{u.email}</p>
                                  </div>
                                </div>
                              ))}
                              {searchLoading && searchMatches.length === 0 && (
                                <p className="px-3 py-2.5 text-xs text-outline">Searching…</p>
                              )}
                              {!searchLoading && searchMatches.length === 0 && (
                                <p className="px-3 py-2.5 text-xs text-outline">No matching members found</p>
                              )}
                            </div>
                          )}
                        </div>
                        <div className="flex gap-2">
                          <button onClick={closeAddMember} className="px-4 py-2 border border-outline-variant rounded-lg text-on-surface-variant hover:bg-surface-container transition-colors font-mono text-xs font-medium">Cancel</button>
                        </div>
                      </div>
                    )}
                  </div>
                </div>

                {/* What each role may do: on request, not in the way. */}
                <button type="button" onClick={() => setRolesOpen((o) => !o)} className="group flex items-center gap-1 text-caption text-secondary">
                  <Icon name={rolesOpen ? 'expand_less' : 'help'} size={14} /><span className="group-hover:underline">What can each role do?</span>
                </button>
                {rolesOpen && (
                  <div className="grid grid-cols-2 gap-3">
                    <div className="flex items-start gap-3 p-3.5 bg-surface-container-low border border-outline-variant rounded-xl">
                      <div className="w-8 h-8 rounded-lg bg-primary-container flex items-center justify-center flex-shrink-0">
                        <Icon name="manage_accounts" size={16} fill className="text-on-primary-container" />
                      </div>
                      <div>
                        <p className="text-on-surface font-mono text-xs font-semibold">Admin</p>
                        <p className="text-on-surface-variant text-caption mt-0.5 leading-[1.5]">Creates project, manages config, runs analysis, approves &amp; publishes docs</p>
                      </div>
                    </div>
                    <div className="flex items-start gap-3 p-3.5 bg-surface-container-low border border-outline-variant rounded-xl">
                      <div className="w-8 h-8 rounded-lg bg-secondary-container flex items-center justify-center flex-shrink-0">
                        <Icon name="engineering" size={16} fill className="text-secondary" />
                      </div>
                      <div>
                        <p className="text-on-surface font-mono text-xs font-semibold">Developer</p>
                        <p className="text-on-surface-variant text-caption mt-0.5 leading-[1.5]">Requests analysis runs, reviews &amp; edits assigned documents</p>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* ══ STEP 5 — REVIEW & INITIALIZE ══ */}
            {cur === 5 && (
              <div className="space-y-4">
                <Readiness items={readiness} onFix={setCur} />
                <p className="pt-2 font-mono text-label font-bold uppercase tracking-[.08em] text-outline">Details</p>
                {/* Project & Repository */}
                <div className="rev-card">
                  <div className="rev-card-head">
                    <div className="flex items-center gap-2">
                      <Icon name="source_environment" size={15} className="text-on-surface-variant" />
                      <span className="text-on-surface font-mono text-xs font-semibold">Project &amp; Repository</span>
                    </div>
                    <button onClick={() => setCur(1)} className="text-secondary hover:underline font-mono text-caption">Edit</button>
                  </div>
                  <div className="rev-row"><span>Name</span><span>{name.trim() || '—'}</span></div>
                  <div className="rev-row"><span>Repository URL</span><span>{repoUrl.trim() || '—'}</span></div>
                  <div className="rev-row"><span>Branch</span><span>{branch || '—'}</span></div>
                  <div className="rev-row"><span>Access Token</span><span>{token ? '••••••••' : 'Not set'}</span></div>
                </div>

                {/* Cores */}
                <div className="rev-card">
                  <div className="rev-card-head">
                    <div className="flex items-center gap-2">
                      <Icon name="memory" size={15} className="text-on-surface-variant" />
                      <span className="text-on-surface font-mono text-xs font-semibold">Cores</span>
                    </div>
                    <button onClick={() => setCur(2)} className="text-secondary hover:underline font-mono text-caption">Edit</button>
                  </div>
                  <CoresReview cores={cores} layers={layers} />
                  {imported && settingsSummary(imported.preview.draft.settings) && (
                    <div className="px-4 py-3 border-t border-surface-container-low flex items-start justify-between gap-3">
                      <span className="font-mono text-caption font-semibold text-on-surface-variant flex-shrink-0">From {imported.fileName}</span>
                      <span className="font-mono text-caption font-medium text-on-surface text-right">{settingsSummary(imported.preview.draft.settings)}</span>
                    </div>
                  )}
                </div>

                {/* Architecture */}
                <div className="rev-card">
                  <div className="rev-card-head">
                    <div className="flex items-center gap-2">
                      <Icon name="account_tree" size={15} className="text-on-surface-variant" />
                      <span className="text-on-surface font-mono text-xs font-semibold">Architecture</span>
                    </div>
                    <button onClick={() => setCur(3)} className="text-secondary hover:underline font-mono text-caption">Edit</button>
                  </div>
                  <div className="rev-row"><span>Layers</span><span>{layers.length} layer{layers.length !== 1 ? 's' : ''} · {totalComps} component{totalComps !== 1 ? 's' : ''}</span></div>
                  <div className="rev-row">
                    <span>Paths</span>
                    <span className={treeReady && !problems.length ? 'text-[#00a572]' : 'text-error'}>
                      {!treeReady ? 'not checked: the repository could not be read'
                        : problems.length ? `${problems.length} to fix in step 3`
                          : `all on branch ${branch}`}
                    </span>
                  </div>
                  <button onClick={() => setReviewTreeOpen((o) => !o)} className="w-full flex items-center gap-1.5 px-4 py-2.5 border-t border-outline-variant text-left font-mono text-caption text-secondary hover:bg-surface-container-low">
                    <Icon name={reviewTreeOpen ? 'expand_less' : 'expand_more'} size={15} />
                    {reviewTreeOpen ? 'Hide the layers' : 'Show every layer, group and component'}
                  </button>
                  {reviewTreeOpen && (
                    layers.length === 0 ? (
                      <p className="px-4 py-3 font-mono text-caption text-outline">No layers defined.</p>
                    ) : (
                      <div className="border-t border-outline-variant">
                        {layers.map((layer) => (
                          <div key={layer.id} className="px-4 py-2.5">
                            <div className="flex items-center gap-1.5 mb-1">
                              <Icon name="layers" size={14} className="text-secondary" />
                              <span className="font-mono text-caption font-bold text-on-surface">{layer.name}</span>
                              {layer.path && <span className="font-mono text-micro text-outline ml-1.5 overflow-hidden text-ellipsis whitespace-nowrap">{layer.path}</span>}
                            </div>
                            {layer.libPaths.filter(Boolean).length > 0 && (
                              <div className="flex items-center flex-wrap gap-1 ml-4 mb-1">
                                {layer.libPaths.filter(Boolean).map((p, i) => (
                                  <span key={i} className="inline-flex items-center gap-[3px] bg-[#f0faf6] border border-[rgba(0,165,114,.2)] rounded-lg px-[7px] py-0.5 font-mono text-micro text-[#006e45]">
                                    <Icon name="folder" size={10} className="text-[#00a572]" />{p}
                                  </span>
                                ))}
                              </div>
                            )}
                            {layer.groups.length === 0 ? (
                              <div className="ml-5 font-mono text-label text-outline">No groups defined</div>
                            ) : layer.groups.map((g) => (
                              <div key={g.id} className="ml-4 border-l-2 border-surface-container pl-2 mt-1">
                                <div className="flex items-center gap-[5px] py-[3px]">
                                  <Icon name="folder_open" size={13} className="text-secondary" />
                                  <span className="font-mono text-label font-semibold text-on-surface">{g.name}</span>
                                  <span className="font-mono text-micro text-outline ml-1">{g.comps.length} comp{g.comps.length !== 1 ? 's' : ''}</span>
                                </div>
                                {g.comps.length === 0 ? (
                                  <div className="ml-[18px] font-mono text-label text-[#b0b3b8] py-0.5">No components</div>
                                ) : g.comps.map((c) => (
                                  <div key={c.id} className="ml-4 border-l-2 border-surface-container-low pl-2 mt-[3px]">
                                    <div className="flex items-center gap-[5px] py-0.5">
                                      <Icon name="folder" size={12} className="text-secondary opacity-75" />
                                      <span className="font-mono text-label text-on-surface">{c.name}</span>
                                      {c.files.length > 0 && <span className="font-mono text-micro text-secondary bg-surface-container px-[5px] py-px rounded-[3px] ml-1">{c.files.length} file{c.files.length !== 1 ? 's' : ''}</span>}
                                    </div>
                                    {c.files.map((f) => (
                                      <div key={f} className="ml-[18px] flex items-center gap-1 py-px">
                                        <Icon name="description" size={11} className="text-[#b0b3b8]" />
                                        <span className="font-mono text-micro text-on-surface-variant">{f.split('/').pop()}</span>
                                      </div>
                                    ))}
                                  </div>
                                ))}
                              </div>
                            ))}
                          </div>
                        ))}
                      </div>
                    )
                  )}
                </div>

                {/* Team */}
                <div className="rev-card">
                  <div className="rev-card-head">
                    <div className="flex items-center gap-2">
                      <Icon name="group" size={15} className="text-on-surface-variant" />
                      <span className="text-on-surface font-mono text-xs font-semibold">Team</span>
                    </div>
                    <button onClick={() => setCur(4)} className="text-secondary hover:underline font-mono text-caption">Edit</button>
                  </div>
                  {(() => {
                    const total = 1 + members.length
                    const admins = 1 + members.filter((m) => m.role === 'Admin').length
                    const devs = members.filter((m) => m.role === 'Developer').length
                    const parts = [`${total} member${total !== 1 ? 's' : ''}`]
                    if (admins) parts.push(`${admins} admin${admins !== 1 ? 's' : ''}`)
                    if (devs) parts.push(`${devs} developer${devs !== 1 ? 's' : ''}`)
                    return <div className="rev-row"><span>Members</span><span>{parts.join(' · ')}</span></div>
                  })()}
                  <div>
                    {[{ name: me.name, email: me.email, role: 'Admin' as Role, you: true }, ...members.map((m) => ({ ...m, you: false }))].map((m) => (
                      <div key={m.email} className="flex items-center gap-2.5 px-4 py-2.5 border-b border-surface-container-low">
                        <div className={cn('w-[30px] h-[30px] rounded-full flex items-center justify-center flex-shrink-0', m.role === 'Admin' ? 'bg-primary-container' : 'bg-secondary')}>
                          <span className="font-mono text-micro font-bold text-white tracking-[.04em]">{memberInitials(m)}</span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="font-sans text-xs font-medium text-on-surface whitespace-nowrap overflow-hidden text-ellipsis">{m.name || m.email}{m.you && <span className="text-on-surface-variant font-normal"> (you)</span>}</div>
                          <div className="font-mono text-label text-outline mt-px">{m.email}</div>
                        </div>
                        <span className={cn('flex-shrink-0 font-mono text-micro font-bold uppercase tracking-[.06em] px-[7px] py-0.5 rounded-[3px]', m.role === 'Admin' ? 'bg-primary-container text-on-primary-container' : 'bg-surface-container text-secondary')}>{m.role}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Action bar */}
        <div className="h-16 flex-shrink-0 bg-white border-t border-outline-variant flex items-center justify-between px-8 gap-4">
          {/* What this step needs - or what still stops it. (Nothing is saved until Initialize.) */}
          {attempted.has(cur) && issuesFor(cur).length > 0 ? (
            <div className="flex items-center gap-1.5 text-error min-w-0">
              <Icon name="error" size={14} fill />
              <span className="font-mono text-caption font-medium truncate">
                {issuesFor(cur).length === 1 ? 'One thing' : `${issuesFor(cur).length} things`} to fix in this step
              </span>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-on-surface-variant min-w-0">
              <Icon name="info" size={14} />
              <span className="font-mono text-caption font-medium truncate">{STEP_HINTS[cur - 1]}</span>
            </div>
          )}
          <div className="flex items-center gap-3">
            <button onClick={back} className={cn('flex items-center gap-2 px-5 py-2.5 border border-outline-variant rounded-lg font-mono text-xs font-medium tracking-[0.02em] text-on-surface-variant hover:bg-surface-container transition-colors', cur === 1 && 'invisible')}>
              <Icon name="arrow_back" size={16} />
              Back
            </button>
            <button onClick={cont} disabled={submitting} className={cn('flex items-center gap-2 px-6 py-2.5 rounded-lg font-mono text-xs font-medium tracking-[0.02em] text-white transition-all active:scale-[.98] disabled:opacity-60', isLast ? 'bg-on-tertiary-container' : 'bg-secondary')}>
              {isLast
                ? <><Icon name="rocket_launch" size={16} fill />{submitting ? 'Initializing…' : 'Initialize Project'}</>
                : <>{cur === 4 && members.length === 0 ? 'Skip for now' : 'Continue'}<Icon name="arrow_forward" size={16} /></>}
            </button>
          </div>
        </div>
      </div>

      {/* Add-Component right panel */}
      {compPanel && (
        <>
          <div className="fixed inset-0 z-[99] bg-[rgba(4,22,39,.25)]" onClick={closeCompPanel} />
          <aside className="fixed top-0 right-0 h-screen bg-white border-l border-outline-variant z-[100] flex flex-col w-[340px] shadow-[-4px_0_24px_rgba(4,22,39,.12)]">
            <div className="flex items-center justify-between px-5 py-4 border-b border-outline-variant flex-shrink-0">
              <div>
                <h3 className="text-on-surface font-sans text-sm font-semibold">Add Component</h3>
                <p className="text-on-surface-variant mt-0.5 text-caption font-mono">Layer root: {panelLayer?.path || panelLayer?.name || '—'}</p>
              </div>
              <button onClick={closeCompPanel} className="p-1.5 text-on-surface-variant hover:text-on-surface hover:bg-surface-container rounded-lg transition-colors">
                <Icon name="close" size={20} />
              </button>
            </div>

            <div className="px-4 py-3 border-b border-outline-variant flex-shrink-0">
              <div className="lbl mb-1.5">Component Name <span className="req">*</span></div>
              <input autoFocus className="inp" value={compName} onChange={(e) => setCompName(e.target.value)} type="text" placeholder="e.g. TorqueManager" />
            </div>

            <div className="flex-1 overflow-y-auto px-3 py-3">
              <div className="sect-label mb-2">Select files / folders</div>
              {repoTreeLoading
                ? <TreeLoading />
                : compTree.map((node) => renderTreeNode(node))}
            </div>

            <div className="px-4 py-3 border-t border-outline-variant flex items-center gap-3 flex-shrink-0">
              <span className="flex-1 text-on-surface-variant font-mono text-caption">{selectedFiles.size} file{selectedFiles.size !== 1 ? 's' : ''} selected</span>
              <button onClick={closeCompPanel} className="px-3 py-2 border border-outline-variant text-on-surface-variant rounded-lg hover:bg-surface-container transition-colors font-mono text-xs font-medium">Cancel</button>
              <button onClick={confirmAddComponent} className="px-4 py-2 bg-secondary text-on-secondary rounded-lg hover:bg-secondary-container transition-colors font-mono text-xs font-medium">Add</button>
            </div>
          </aside>
        </>
      )}

      {/* Browse folder-picker */}
      {fpTarget && (
        <>
          <div className="fixed inset-0 z-[99] bg-[rgba(4,22,39,.25)]" onClick={() => setFpTarget(null)} />
          <aside className="fixed top-0 right-0 h-screen bg-white border-l border-outline-variant z-[100] flex flex-col w-[320px] shadow-[-4px_0_24px_rgba(4,22,39,.12)]">
            <div className="flex items-center justify-between px-5 py-4 border-b border-outline-variant flex-shrink-0">
              <div className="min-w-0">
                <h3 className="text-on-surface font-sans text-sm font-semibold">Select Folder</h3>
                <p className="text-on-surface-variant mt-0.5 truncate text-caption font-mono">{fpDisplay}</p>
              </div>
              <button onClick={() => setFpTarget(null)} className="p-1.5 text-on-surface-variant hover:text-on-surface hover:bg-surface-container rounded-lg transition-colors flex-shrink-0">
                <Icon name="close" size={20} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-3">
              <div className="sect-label mb-2">Project root · {repoRoot}</div>
              {repoTreeLoading
                ? <TreeLoading />
                : pickerTree.map((node) => renderFpNode(node))}
            </div>
            <div className="px-4 py-3 border-t border-outline-variant flex gap-3 flex-shrink-0">
              <button onClick={() => setFpTarget(null)} className="px-4 py-2 border border-outline-variant text-on-surface-variant rounded-lg hover:bg-surface-container transition-colors font-mono text-xs font-medium">Cancel</button>
              <button onClick={confirmFolderPicker} disabled={!fpSelected} className="flex-1 py-2 bg-secondary text-on-secondary rounded-lg hover:bg-secondary-container transition-colors disabled:opacity-60 font-mono text-xs font-medium">Select Folder</button>
            </div>
          </aside>
        </>
      )}
    </div>
  )

  /* Recursive file-tree node for the Add-Component panel. */
  function renderTreeNode(node: RepoEntry) {
    if (node.type === 'file') {
      const owner = ownerOf(node.path, fileAssignments)
      const assigned = !!owner
      return (
        <div key={node.path} className={`sidebar-file-row ${assigned ? 'assigned' : ''}`} onClick={() => !assigned && toggleFile(node.path)}>
          <input type="checkbox" className={cn('file-cb', TREE_CB)} disabled={assigned} checked={selectedFiles.has(node.path)} onChange={() => toggleFile(node.path)} onClick={(e) => e.stopPropagation()} />
          <Icon name="description" size={13} className="text-on-surface-variant" />
          <span className="flex-1 font-mono text-caption text-on-surface">{node.name}</span>
          {assigned && <span className="file-owner-tag">{owner}</span>}
        </div>
      )
    }
    const children = node.children ?? []
    const open = !!treeOpen[node.path]
    const files = descendantFiles(node).filter((f) => !ownerOf(f, fileAssignments))
    const sel = files.filter((f) => selectedFiles.has(f)).length
    const checked = files.length > 0 && sel === files.length
    const indeterminate = sel > 0 && sel < files.length
    const isRoot = node.name === compRoot
    return (
      <div key={node.path} className="sidebar-folder-block">
        <div className="sidebar-folder-row" onClick={() => toggleFolder(node)}>
          <button onClick={(e) => { e.stopPropagation(); setTreeOpen((p) => ({ ...p, [node.path]: !p[node.path] })) }} className="tree-toggle">
            <Icon name={open ? 'keyboard_arrow_down' : 'keyboard_arrow_right'} size={14} />
          </button>
          <input type="checkbox" className={cn('folder-cb', TREE_CB)} checked={checked} ref={(el) => { if (el) el.indeterminate = indeterminate }} onChange={() => toggleFolder(node)} onClick={(e) => e.stopPropagation()} />
          <Icon name={isRoot ? 'account_tree' : open ? 'folder_open' : 'folder'} size={15} className="text-secondary" />
          <span className={cn('flex-1 font-mono text-caption text-on-surface', isRoot ? 'font-semibold' : 'font-normal')}>{node.name}</span>
        </div>
        {open && (
          <div className="pl-5">
            {children.length === 0
              ? <div className="px-2 py-1.5 text-on-surface-variant font-mono text-caption">No files found in this path.</div>
              : children.map((c) => renderTreeNode(c))}
          </div>
        )}
      </div>
    )
  }

  /* Recursive folder node for the Browse folder-picker. */
  function renderFpNode(node: RepoEntry) {
    const children = node.children ?? []
    const hasChildren = children.length > 0
    const open = !!fpOpen[node.path]
    const selected = fpSelected === node.path
    return (
      <div key={node.path}>
        <div className={`fp-folder-row ${selected ? 'selected' : ''}`} onClick={() => { setFpSelected(node.path); if (hasChildren && !open) setFpOpen((p) => ({ ...p, [node.path]: true })) }}>
          <button className={cn('tree-toggle', !hasChildren && 'invisible')} onClick={(e) => { e.stopPropagation(); setFpOpen((p) => ({ ...p, [node.path]: !p[node.path] })) }}>
            <Icon name={open ? 'keyboard_arrow_down' : 'keyboard_arrow_right'} size={14} />
          </button>
          <Icon name={node.path === '.' ? 'account_tree' : open ? 'folder_open' : 'folder'} size={15} className="text-secondary" />
          <span className={cn('flex-1 font-mono text-caption text-on-surface', node.path === '.' ? 'font-semibold' : 'font-normal')}>{node.name}/</span>
        </div>
        {hasChildren && open && <div className="fp-children">{children.map((c) => renderFpNode(c))}</div>}
      </div>
    )
  }
}

/* ─── Page ──────────────────────────────────────────────────────────── */
// The "no projects yet" empty state now lives on ProjectsPage; this route is
// the create-project wizard, reached via the empty state's "New Project" card.
export function NewProjectPage() {
  const navigate = useNavigate()
  const createProject = useCreateProject()
  const [step, setStep] = useState(1)

  async function handleSubmit(data: CreateProjectInput) {
    try {
      const project = await createProject.mutateAsync(data)
      clearDraft()
      navigate(`/projects/${project.id}/overview`)
    } catch {
      /* error toast handled by the mutation; the draft stays */
    }
  }
  // Leaving the wizard by its own buttons drops the draft; a reload keeps it.
  function leave() {
    clearDraft()
    navigate('/projects')
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <PageHeader step={step} onBack={leave} backLabel="Back to Projects" />
      <WizardView
        onCancel={leave}
        onSubmit={handleSubmit}
        submitting={createProject.isPending}
        onStepChange={setStep}
      />
    </div>
  )
}
