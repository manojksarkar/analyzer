import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateProject } from '../hooks/useProjects'
import { useRepositoryWizard } from '../hooks/useRepositoryWizard'
import { useAuthStore } from '../store/auth'
import { Icon, BrandMark, toast } from '../components/ui'
import { cn } from '../lib/cn'
import { APP_NAME, APP_TAGLINE } from '../constants/branding'
import type { CreateProjectInput, RepoEntry, OrgUser } from '../services/api'

// Rail entries — short title + sub, mirroring the design's step rail.
const STEPS = [
  { title: 'Project & Repository', sub: 'Name, source path' },
  { title: 'Build Configuration',  sub: 'Defines & data dictionary' },
  { title: 'Architecture',         sub: 'Layers & groups' },
  { title: 'Team & Access',        sub: 'Add developers' },
  { title: 'Review & Initialize',  sub: 'Confirm & create project' },
]

// Per-step content header (longer description shown above the form fields).
const STEP_HEADERS = [
  { title: 'Project & Repository', sub: 'Name the project and connect your source repository.' },
  { title: 'Build Configuration',  sub: 'Preprocessor definitions and optional data dictionary.' },
  { title: 'Architecture Mapping', sub: 'Map layers and groups. Components are discovered automatically from source folders.' },
  { title: 'Team & Access',        sub: 'Add team members and assign their role. More members can be added later from Project Settings.' },
  { title: 'Review & Initialize',  sub: 'Confirm every setting before the first analysis run.' },
]

const TREE_CB = 'w-3.5 h-3.5 accent-secondary cursor-pointer flex-shrink-0'

type Role = 'Admin' | 'Developer'
type TestTone = 'neutral' | 'error' | 'ok'
interface Member { name?: string; email: string; role: Role }
interface Comp { id: string; name: string; files: string[]; collapsed: boolean }
interface Group { id: string; name: string; comps: Comp[]; collapsed: boolean }
interface Layer { id: string; name: string; path: string; groups: Group[]; libPaths: string[]; collapsed: boolean }

// The source tree comes from the real GET /repositories/browse endpoint
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

let _uid = 0
const uid = () => `id${++_uid}`

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
  cur, done, onClose, onGo,
}: { cur: number; done: Set<number>; onClose: () => void; onGo: (n: number) => void }) {
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
              </div>
              <div className="pt-[3px]">
                <p className={cn('font-mono text-xs leading-[1.2]', n === cur ? 'text-secondary font-semibold' : done.has(n) ? 'text-on-surface font-medium' : 'text-on-surface-variant font-medium')}>{s.title}</p>
                <p className={cn('font-mono text-caption mt-0.5', n === cur ? 'text-secondary' : 'text-outline')}>{s.sub}</p>
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

/* ─── Wizard ────────────────────────────────────────────────────────── */
function WizardView({
  onCancel, onSubmit, submitting, onStepChange,
}: { onCancel: () => void; onSubmit: (data: CreateProjectInput) => void; submitting: boolean; onStepChange: (n: number) => void }) {
  const repo = useRepositoryWizard()
  // 1-based step + `done` set (steps advanced past) — drives the rail + bar.
  const [cur, setCur] = useState(1)
  const [done, setDone] = useState<Set<number>>(new Set())
  const scrollRef = useRef<HTMLDivElement>(null)
  // The pinned "self" row uses the real logged-in user (admin/creator).
  const authUser = useAuthStore((s) => s.user)
  const me = { name: authUser?.name ?? 'You', email: authUser?.email ?? '', initials: authUser?.initials ?? 'YOU' }

  // ── Step 1: project & repository ──
  const [name, setName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [token, setToken] = useState('')
  const [showToken, setShowToken] = useState(false)
  const [branch, setBranch] = useState('')
  const [branches, setBranches] = useState<string[]>([])
  const [testState, setTestState] = useState<'idle' | 'connecting' | 'connected'>('idle')
  const [testMsg, setTestMsg] = useState<{ text: string; tone: TestTone } | null>(null)
  const [errs, setErrs] = useState<{ name?: boolean; repo?: boolean; branch?: boolean }>({})
  // Source tree fetched from /repositories/browse after a successful connection.
  const [repoTree, setRepoTree] = useState<RepoEntry[]>([])
  // True while the (blobless) clone + tree fetch is in flight — drives the
  // loaders in the Add-Component panel and the folder picker.
  const [repoTreeLoading, setRepoTreeLoading] = useState(false)

  // ── Step 2: build configuration ──
  const [defTab, setDefTab] = useState<'upload' | 'manual'>('upload')
  const [defFileName, setDefFileName] = useState('')
  const [defFileId, setDefFileId] = useState('')
  const [defManual, setDefManual] = useState('')
  const [ddFile, setDdFile] = useState<{ name: string; size: number; id: string } | null>(null)
  const defInputRef = useRef<HTMLInputElement>(null)
  const ddInputRef = useRef<HTMLInputElement>(null)

  // ── Step 3: architecture ──
  const [layers, setLayers] = useState<Layer[]>([])
  const [addLayerOpen, setAddLayerOpen] = useState(false)
  const [newLayerName, setNewLayerName] = useState('')
  const [newLayerPath, setNewLayerPath] = useState('')
  const [inlineAdd, setInlineAdd] = useState<{ parentId: string } | null>(null)
  const [inlineVal, setInlineVal] = useState('')
  // Add-Component right panel
  const [compPanel, setCompPanel] = useState<{ layerId: string; groupId: string } | null>(null)
  const [compName, setCompName] = useState('')
  const [selectedFiles, setSelectedFiles] = useState<Set<string>>(new Set())
  const [treeOpen, setTreeOpen] = useState<Record<string, boolean>>({ 'src/': true })
  const [fileAssignments, setFileAssignments] = useState<Record<string, string>>({})
  // Browse folder-picker
  type FpTarget = { kind: 'new-layer-path' } | { kind: 'lib-path'; layerId: string; index: number }
  const [fpTarget, setFpTarget] = useState<FpTarget | null>(null)
  const [fpSelected, setFpSelected] = useState('')
  const [fpOpen, setFpOpen] = useState<Record<string, boolean>>({})

  // ── Step 4: team ──
  const [members, setMembers] = useState<Member[]>([])
  const [addMemberOpen, setAddMemberOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [searchOpen, setSearchOpen] = useState(false)
  const [inviteRole, setInviteRole] = useState<Role>('Developer')
  // Org directory results from GET /users/search (debounced as the user types).
  const [searchResults, setSearchResults] = useState<OrgUser[]>([])
  const [searchLoading, setSearchLoading] = useState(false)

  // ── Step 5: review ──
  const [definesExpanded, setDefinesExpanded] = useState(false)

  // Reset scroll to top on step change, and report active step up to the top bar.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: 0 })
    onStepChange(cur)
    if (cur === 5) setDefinesExpanded(false)
  }, [cur, onStepChange])

  /* ── Step 1 helpers ── */
  function repoChanged() {
    setTestState('idle')
    setTestMsg(null)
    setBranches([])
    setBranch('')
    setRepoTree([])
  }
  // Load the source tree for a specific branch/ref (architecture + folder pickers).
  // Re-run whenever the selected branch changes so the tree matches the branch.
  async function loadRepoTree(ref: string) {
    setRepoTreeLoading(true)
    try {
      setRepoTree(await repo.browse(repoUrl.trim(), ref || undefined, '', token.trim() || undefined))
    } catch {
      setRepoTree([])
    } finally {
      setRepoTreeLoading(false)
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
      const initialBranch = res.defaultBranch || res.branches[0] || ''
      setBranches(res.branches)
      setBranch(initialBranch)
      setTestState('connected')
      setTestMsg({ text: res.message, tone: 'ok' })
      // Pre-fetch the source tree for the architecture + folder pickers.
      await loadRepoTree(initialBranch)
    } catch (e) {
      setTestState('idle')
      setTestMsg({ text: (e as Error).message || 'Connection failed.', tone: 'error' })
      setBranches([]); setBranch(''); setRepoTree([])
    }
  }

  /* ── Step 2 helpers — upload build-config files to /repositories/uploads ── */
  async function uploadDef(f: File) {
    setDefFileName(f.name)
    try {
      const u = await repo.upload(f, 'preprocessor_definitions')
      setDefFileId(u.id)
    } catch (e) {
      setDefFileName(''); setDefFileId('')
      toast.error('Upload failed', (e as Error).message)
    }
  }
  async function uploadDd(f: File) {
    try {
      const u = await repo.upload(f, 'data_dictionary')
      setDdFile({ name: u.fileName, size: u.size, id: u.id })
    } catch (e) {
      toast.error('Upload failed', (e as Error).message)
    }
  }

  /* ── Step 3 helpers ── */
  function confirmAddLayer() {
    const nm = newLayerName.trim().toUpperCase().replace(/\s+/g, '_')
    if (!nm) return
    setLayers((prev) => [...prev, { id: uid(), name: nm, path: newLayerPath.trim(), groups: [], libPaths: [], collapsed: false }])
    setNewLayerName(''); setNewLayerPath(''); setAddLayerOpen(false)
  }
  const patchLayer = (id: string, fn: (l: Layer) => Layer) =>
    setLayers((prev) => prev.map((l) => (l.id === id ? fn(l) : l)))
  function confirmGroup() {
    const v = inlineVal.trim()
    if (!v || !inlineAdd) return
    patchLayer(inlineAdd.parentId, (l) => ({ ...l, groups: [...l.groups, { id: uid(), name: v, comps: [], collapsed: false }] }))
    setInlineAdd(null); setInlineVal('')
  }
  function freeFiles(files: string[]) {
    setFileAssignments((prev) => { const next = { ...prev }; files.forEach((f) => delete next[f]); return next })
  }
  function removeGroup(layerId: string, g: Group) {
    freeFiles(g.comps.flatMap((c) => c.files))
    patchLayer(layerId, (l) => ({ ...l, groups: l.groups.filter((x) => x.id !== g.id) }))
  }
  function removeLayer(layer: Layer) {
    freeFiles(layer.groups.flatMap((g) => g.comps.flatMap((c) => c.files)))
    setLayers((prev) => prev.filter((l) => l.id !== layer.id))
  }
  function removeComp(layerId: string, groupId: string, comp: Comp) {
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
    const files = descendantFiles(node).filter((f) => !fileAssignments[f])
    const allSel = files.length > 0 && files.every((f) => selectedFiles.has(f))
    setSelectedFiles((prev) => { const next = new Set(prev); files.forEach((f) => (allSel ? next.delete(f) : next.add(f))); return next })
    if (!allSel) setTreeOpen((prev) => ({ ...prev, [node.path]: true }))
  }
  function confirmAddComponent() {
    const nm = compName.trim()
    if (!nm || !compPanel) return
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
  const pickerTree: RepoEntry[] = [{ type: 'folder', name: repoRoot, path: '.', children: foldersOnly(repoTree) }]
  const fpDisplay = fpSelected ? (fpSelected === '.' ? repoRoot : `${repoRoot}/${fpSelected}`) : 'No folder selected'
  function openFolderPicker(target: FpTarget) {
    setFpTarget(target); setFpSelected('')
    // Expand the project root + its first level by default.
    setFpOpen({ '.': true, ...Object.fromEntries(foldersOnly(repoTree).map((n) => [n.path, true])) })
  }
  function confirmFolderPicker() {
    if (!fpSelected || !fpTarget) return
    if (fpTarget.kind === 'new-layer-path') setNewLayerPath(fpSelected)
    else patchLayer(fpTarget.layerId, (l) => ({ ...l, libPaths: l.libPaths.map((x, i) => (i === fpTarget.index ? fpSelected : x)) }))
    setFpTarget(null)
  }
  const totalComps = layers.reduce((a, l) => a + l.groups.reduce((b, g) => b + g.comps.length, 0), 0)

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
  function validate(n: number): boolean {
    if (n === 1) {
      const e: typeof errs = {}
      if (!name.trim()) e.name = true
      if (!repoUrl.trim()) e.repo = true
      if (e.name || e.repo) { setErrs(e); return false }
      if (testState !== 'connected') {
        setTestMsg({ text: 'Test the connection first to load branches.', tone: 'error' })
        return false
      }
      if (!branch) { setErrs({ branch: true }); return false }
      setErrs({})
    }
    return true
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
          preprocessor_definitions: defTab === 'upload'
            ? { mode: 'upload', file_name: defFileName || null, file_id: defFileId || null }
            : { mode: 'manual', defines: defManual.split('\n').map((s) => s.trim()).filter(Boolean) },
          data_dictionary: ddFile ? { file_name: ddFile.name, file_id: ddFile.id } : null,
        },
        architecture_layers: layers.map((l) => ({
          name: l.name,
          path: l.path,
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

  const isLast = cur === STEPS.length
  const testMsgCls = testMsg?.tone === 'error' ? 'text-error' : testMsg?.tone === 'ok' ? 'text-[#00a572]' : 'text-on-surface-variant'

  return (
    <div className="flex-1 overflow-hidden flex">
      <StepRail cur={cur} done={done} onClose={onCancel} onGo={railGo} />

      {/* Form area */}
      <div className="flex-1 flex flex-col overflow-hidden bg-background">
        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="max-w-2xl mx-auto px-6 py-6 space-y-5">
            <StepHeader title={STEP_HEADERS[cur - 1].title} sub={STEP_HEADERS[cur - 1].sub} />

            {/* ══ STEP 1 — PROJECT & REPOSITORY ══ */}
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

                <div>
                  <div className="lbl">
                    Access Token
                    <span className="ml-auto text-on-surface-variant font-mono text-caption font-normal tracking-normal normal-case">Optional — for private repos</span>
                  </div>
                  <div className="relative">
                    <input className="inp mono pr-10" value={token} onChange={(e) => { setToken(e.target.value); repoChanged() }} type={showToken ? 'text' : 'password'} placeholder="ghp_xxxxxxxxxxxxxxxxxxxx" />
                    <button type="button" onClick={() => setShowToken((s) => !s)} className="absolute right-3 top-1/2 -translate-y-1/2 text-on-surface-variant hover:text-on-surface transition-colors">
                      <Icon name={showToken ? 'visibility' : 'visibility_off'} size={17} />
                    </button>
                  </div>
                </div>

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
                    <select className={`inp ${errs.branch ? 'err' : ''}`} value={branch} onChange={(e) => { const b = e.target.value; setBranch(b); setErrs((p) => ({ ...p, branch: false })); if (b) loadRepoTree(b) }}>
                      <option value="">Select a branch…</option>
                      {branches.map((b) => <option key={b} value={b}>{b}</option>)}
                    </select>
                  </div>
                )}
              </div>
            )}

            {/* ══ STEP 2 — BUILD CONFIGURATION ══ */}
            {cur === 2 && (
              <div className="grid grid-cols-2 gap-4">
                {/* Preprocessor Definitions */}
                <div className="card">
                  <div className="card-head">
                    <div className="card-head-l">
                      <div className="card-icon bg-primary-container">
                        <Icon name="data_object" size={17} className="text-on-primary-container" />
                      </div>
                      <h3 className="text-on-surface font-sans text-sm font-semibold">Preprocessor Definitions</h3>
                    </div>
                    <button className="flex items-center justify-center rounded-full bg-surface-container-low border border-outline-variant text-on-surface-variant w-[22px] h-[22px]" title="Macro definitions passed as -D flags to Clang.">
                      <Icon name="help" size={13} />
                    </button>
                  </div>

                  {defTab === 'upload' ? (
                    <>
                      <div
                        className={`drop-zone ${defFileName ? 'has-file' : ''}`}
                        onClick={() => defInputRef.current?.click()}
                        onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('dragover') }}
                        onDragLeave={(e) => e.currentTarget.classList.remove('dragover')}
                        onDrop={(e) => { e.preventDefault(); e.currentTarget.classList.remove('dragover'); const f = e.dataTransfer.files[0]; if (f) uploadDef(f) }}
                      >
                        <Icon name="upload_file" size={28} className="text-on-surface-variant mb-2 block" />
                        <p className="text-on-surface mb-1 font-mono text-xs font-medium">Drop Makefile or CSV here</p>
                        <p className="text-on-surface-variant text-xs">Supported: <span className="font-mono text-caption">Makefile, .csv, .mk</span></p>
                      </div>
                      <input ref={defInputRef} type="file" accept=".csv,.mk,Makefile,makefile" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadDef(f) }} />
                      {defFileName && (
                        <div className="mt-3 flex items-center gap-2 px-3 py-2 bg-surface-container-low border border-outline-variant rounded-lg">
                          <Icon name="description" size={18} className="text-secondary" />
                          <span className="text-on-surface flex-1 font-mono text-xs">{defFileName}</span>
                          <button onClick={() => { setDefFileName(''); setDefFileId(''); if (defInputRef.current) defInputRef.current.value = '' }} className="text-on-surface-variant hover:text-error transition-colors">
                            <Icon name="close" size={16} />
                          </button>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="lbl mb-2 mt-0">One definition per line — KEY or KEY=VALUE</div>
                      <textarea className="inp mono" rows={5} value={defManual} onChange={(e) => setDefManual(e.target.value)} placeholder={'DEBUG=1\nPLATFORM=QNX\nASPICE_LEVEL_2\nMAX_INPUTS=64'} />
                    </>
                  )}

                  <div className="flex gap-2 mt-4 pt-3 border-t border-outline-variant">
                    <button className={`tab-btn ${defTab === 'upload' ? 'on' : ''}`} onClick={() => setDefTab('upload')}>
                      <Icon name="upload_file" size={13} className="align-middle mr-[3px]" />Upload
                    </button>
                    <button className={`tab-btn ${defTab === 'manual' ? 'on' : ''}`} onClick={() => setDefTab('manual')}>
                      <Icon name="edit_note" size={13} className="align-middle mr-[3px]" />Manual
                    </button>
                  </div>
                </div>

                {/* Data Dictionary */}
                <div className="card">
                  <div className="card-head">
                    <div className="card-head-l">
                      <div className="card-icon bg-tertiary-container">
                        <Icon name="menu_book" size={17} className="text-tertiary-fixed" />
                      </div>
                      <div>
                        <h3 className="text-on-surface font-sans text-sm font-semibold">Data Dictionary</h3>
                        <p className="text-on-surface-variant text-caption mt-0.5">Signal names, units, ranges</p>
                      </div>
                    </div>
                  </div>

                  <div
                    className={`drop-zone ${ddFile ? 'has-file' : ''}`}
                    onClick={() => ddInputRef.current?.click()}
                    onDragOver={(e) => { e.preventDefault(); e.currentTarget.classList.add('dragover') }}
                    onDragLeave={(e) => e.currentTarget.classList.remove('dragover')}
                    onDrop={(e) => { e.preventDefault(); e.currentTarget.classList.remove('dragover'); const f = e.dataTransfer.files[0]; if (f) uploadDd(f) }}
                  >
                    <Icon name="cloud_upload" size={28} className="text-on-surface-variant mb-2 block" />
                    <p className="text-on-surface mb-1 font-mono text-xs font-medium">Drop CSV or Excel here</p>
                    <p className="text-on-surface-variant text-xs">Supported: <span className="font-mono text-caption">.csv, .xlsx</span> · Optional</p>
                  </div>
                  <input ref={ddInputRef} type="file" accept=".csv,.xlsx,.xls" className="hidden" onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadDd(f) }} />
                  {ddFile && (
                    <div className="mt-3 flex items-center gap-3 px-3 py-2.5 bg-surface-container-low border border-[rgba(0,165,114,.3)] rounded-xl">
                      <Icon name="description" size={20} fill className="text-[#00a572]" />
                      <div className="flex-1 min-w-0">
                        <div className="text-on-surface font-mono text-xs">{ddFile.name}</div>
                        <div className="text-on-surface-variant font-mono text-caption">{(ddFile.size / 1024).toFixed(1)} KB</div>
                      </div>
                      <button onClick={() => { setDdFile(null); if (ddInputRef.current) ddInputRef.current.value = '' }} className="text-on-surface-variant hover:text-error transition-colors p-1">
                        <Icon name="close" size={18} />
                      </button>
                    </div>
                  )}

                  <p className="text-on-surface-variant mt-3 text-caption">Skipping is fine — you can upload a data dictionary later from Project Settings.</p>
                </div>
              </div>
            )}

            {/* ══ STEP 3 — ARCHITECTURE ══ */}
            {cur === 3 && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Icon name="account_tree" size={17} className="text-secondary" />
                    <span className="text-on-surface-variant uppercase font-mono text-xs font-medium tracking-[.08em]">Project Architecture</span>
                  </div>
                  <button onClick={() => setAddLayerOpen(true)} className="flex items-center gap-1.5 px-3 py-1.5 text-secondary border border-outline-variant rounded-lg hover:bg-surface-container-low transition-colors font-mono text-xs font-medium">
                    <Icon name="add" size={15} /> Add Layer
                  </button>
                </div>

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
                          <div className="text-on-surface font-mono text-body font-bold leading-[1.3]">{layer.name}</div>
                          <span className={`layer-path-display ${layer.path ? '' : 'empty'}`}>{layer.path || 'Set root path…'}</span>
                        </div>
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
                                        <button onClick={() => removeComp(layer.id, g.id, c)} className="p-1 text-on-surface-variant hover:text-error transition-colors">
                                          <Icon name="close" size={13} />
                                        </button>
                                      </div>
                                      {c.files.length > 0 && !c.collapsed && (
                                        <div className="comp-files">
                                          {c.files.map((f) => (
                                            <div key={f} className="file-row">
                                              <Icon name="description" size={12} className="text-[#b0b3b8]" />{f.split('/').pop()}
                                            </div>
                                          ))}
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

                          {/* Lib paths */}
                          <div className="inc-paths-section">
                            <div className="inc-paths-row">
                              <div className="inc-paths-label" title="External include paths (-I flags) for this layer.">Lib Paths</div>
                              <div className="inc-paths-content">
                                {layer.libPaths.map((p, idx) => (
                                  <div key={idx} className="ext-path-row">
                                    <Icon name="folder_open" size={13} className="text-[#00a572] flex-shrink-0" />
                                    <input className="ext-path-input" value={p} placeholder="/path/to/include" onChange={(e) => patchLayer(layer.id, (l) => ({ ...l, libPaths: l.libPaths.map((x, i) => i === idx ? e.target.value : x) }))} />
                                    <button type="button" className="ext-browse-btn" onClick={() => openFolderPicker({ kind: 'lib-path', layerId: layer.id, index: idx })}>
                                      <Icon name="folder_open" size={11} />BROWSE
                                    </button>
                                    <button onClick={() => patchLayer(layer.id, (l) => ({ ...l, libPaths: l.libPaths.filter((_, i) => i !== idx) }))} className="flex items-center bg-transparent border-none cursor-pointer p-0 text-outline">
                                      <Icon name="close" size={13} className="leading-none" />
                                    </button>
                                  </div>
                                ))}
                                <button onClick={() => patchLayer(layer.id, (l) => ({ ...l, libPaths: [...l.libPaths, ''] }))} className="inc-add-btn">
                                  <Icon name="add" size={12} className="align-middle" /> Add path
                                </button>
                              </div>
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>

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
                              <input className="inp pl-8" value={search} onChange={(e) => setSearch(e.target.value)} onFocus={() => setSearchOpen(true)} onBlur={() => window.setTimeout(() => setSearchOpen(false), 150)} type="text" autoComplete="off" placeholder="Search by name or email…" />
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

                {/* Role legend */}
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
              </div>
            )}

            {/* ══ STEP 5 — REVIEW & INITIALIZE ══ */}
            {cur === 5 && (
              <div className="space-y-4">
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

                {/* Build Configuration */}
                <div className="rev-card">
                  <div className="rev-card-head">
                    <div className="flex items-center gap-2">
                      <Icon name="data_object" size={15} className="text-on-surface-variant" />
                      <span className="text-on-surface font-mono text-xs font-semibold">Build Configuration</span>
                    </div>
                    <button onClick={() => setCur(2)} className="text-secondary hover:underline font-mono text-caption">Edit</button>
                  </div>
                  {(() => {
                    const manualLines = defManual.split('\n').map((l) => l.trim()).filter(Boolean)
                    const count = defTab === 'upload' ? (defFileName ? '' : 'No file') : (manualLines.length ? `${manualLines.length} definition${manualLines.length !== 1 ? 's' : ''}` : 'empty')
                    return (
                      <div className="px-4 py-2.5 border-b border-surface-container-low">
                        <button onClick={() => setDefinesExpanded((v) => !v)} className="w-full flex items-center gap-1.5 bg-transparent border-none cursor-pointer p-0 text-left">
                          <Icon name={definesExpanded ? 'keyboard_arrow_down' : 'keyboard_arrow_right'} size={15} className="text-outline flex-shrink-0" />
                          <span className="font-mono text-caption font-semibold text-on-surface-variant flex-1">Preprocessor Definitions</span>
                          <span className="font-mono text-label text-outline mr-1.5">{count}</span>
                          <span className="font-mono text-micro font-bold uppercase tracking-[.06em] px-[7px] py-0.5 rounded-[3px] bg-surface-container text-secondary">{defTab === 'upload' ? 'Upload' : 'Manual'}</span>
                        </button>
                        {definesExpanded && (
                          <div className="mt-2 font-mono text-caption">
                            {defTab === 'upload' ? (
                              defFileName ? (
                                <div className="flex items-center gap-1.5 px-2.5 py-1.5 bg-surface-container-low border border-outline-variant rounded-md">
                                  <Icon name="description" size={14} className="text-secondary" />
                                  <span className="text-on-surface">{defFileName}</span>
                                </div>
                              ) : <span className="text-outline">No file selected</span>
                            ) : (
                              manualLines.length ? manualLines.map((l, i) => (
                                <div key={i} className="flex items-center gap-1.5 py-1 border-b border-[#f0f2f8]">
                                  <span className="text-secondary font-bold flex-shrink-0">#</span>
                                  <code className="text-on-surface">{l}</code>
                                </div>
                              )) : <span className="text-outline">No definitions entered</span>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })()}
                  <div className="px-4 py-3">
                    <div className="flex items-center justify-between">
                      <span className="font-mono text-caption font-semibold text-on-surface-variant">Data Dictionary</span>
                      <span className="font-mono text-caption font-medium text-on-surface">{ddFile?.name || 'Not uploaded'}</span>
                    </div>
                  </div>
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
                  {layers.length === 0 ? (
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
          <div className="flex items-center gap-1.5 text-on-surface-variant">
            <Icon name="save" size={14} />
            <span className="font-mono text-caption font-medium">Auto-saved</span>
          </div>
          <div className="flex items-center gap-3">
            <button onClick={back} className={cn('flex items-center gap-2 px-5 py-2.5 border border-outline-variant rounded-lg text-sm text-on-surface-variant hover:bg-surface-container transition-colors', cur === 1 && 'invisible')}>
              <Icon name="arrow_back" size={16} />
              Back
            </button>
            <button onClick={cont} disabled={submitting} className={cn('flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-semibold text-white transition-all active:scale-[.98] disabled:opacity-60', isLast ? 'bg-[#00a572]' : 'bg-secondary')}>
              {isLast
                ? <>{submitting ? 'Initializing…' : 'Initialize Project'}<Icon name="rocket_launch" size={16} fill /></>
                : <>Continue<Icon name="arrow_forward" size={16} /></>}
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
      const owner = fileAssignments[node.path]
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
    const files = descendantFiles(node).filter((f) => !fileAssignments[f])
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
      navigate(`/projects/${project.id}/overview`)
    } catch {
      /* error toast handled by the mutation */
    }
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden">
      <PageHeader step={step} onBack={() => navigate('/projects')} backLabel="Back to Projects" />
      <WizardView
        onCancel={() => navigate('/projects')}
        onSubmit={handleSubmit}
        submitting={createProject.isPending}
        onStepChange={setStep}
      />
    </div>
  )
}
