export type UserRole = 'admin' | 'developer'

export interface AuthUser {
  id: string
  name: string
  email: string
  initials: string
  /** No longer global — role is per-project (see Project.userRole). Kept
   *  optional so legacy reads don't break; always undefined from the API. */
  role?: UserRole
}

/** Returned by authApi.signIn — user plus the JWT pair. */
export interface AuthSession {
  user: AuthUser
  accessToken: string
  refreshToken: string
}

// 'never' = no doc generated yet (API DocStatus). 'complete'/'draft' kept for
// back-compat with existing badge config.
export type DocStatus = 'never' | 'in_review' | 'approved' | 'complete' | 'draft' | 'unchanged'
export type VersionStatus = 'in_review' | 'approved' | 'complete' | 'draft'
export type PageState = 'never' | 'running' | 'in_review' | 'complete' | 'stale'

export interface TeamMember {
  id: string
  /** Backend user id — needed for role-change / remove mutations. */
  userId?: string
  name: string
  initials: string
  email: string
  role: UserRole
  lastActive: string
  avatarColor: string
  avatarTextColor: string
  pending?: boolean
}

/** Architecture captured during project setup (layers → groups → components). */
export interface ArchComponent { name: string; files?: string[] }
export interface ArchGroup { name: string; components: ArchComponent[] }
/** `core`: the core the layer is built for - its files parse with that core's macros and
 *  include paths, and take its data dictionary. */
export interface ArchLayer { name: string; path?: string; libPaths?: string[]; groups: ArchGroup[]; core?: string | null }

/** One of the project's cores - one build of the firmware - as the overview shows it: its
 *  inputs' file names (`N typed` for typed macros) and the layers built for it. A project from
 *  before cores reads as one core, Core1, that every layer uses. */
export interface ProjectCore {
  name: string
  macros: string | null
  dataDictionary: string | null
  compileCommands: string | null
  layers: string[]
}

/** Build configuration summary surfaced on the overview (token-free). */
export interface ProjectBuildConfig {
  cores: ProjectCore[]
}

/** A config file read into the New Project wizard (`POST /projects/config/preview`). */
export type ConfigReportLevel = 'filled' | 'check' | 'skipped'
/** Which part of the wizard an item is about. Once the user changes the architecture, a new
 *  check keeps the old `architecture` items and replaces the rest. */
export type ConfigReportTopic = 'project' | 'architecture' | 'files' | 'settings' | 'repository' | 'other'
export interface ConfigReportItem { level: ConfigReportLevel; text: string; topic: ConfigReportTopic }
/** A build-configuration file stored as an upload. */
export interface UploadedFile { fileId: string; fileName: string; size: number }
/** A core as a config file describes it: its macros (a file found in the repository, or
 *  `project.defines` typed into the file), its data dictionary and its compile commands. */
export interface DraftCore {
  name: string
  macros: { kind: 'file'; file: UploadedFile } | { kind: 'typed'; defines: string[] } | null
  dataDictionary: UploadedFile | null
  compileCommands: UploadedFile | null
}
/** A core's three inputs. */
export interface CoreInputs<T> { macros: T; dataDictionary: T; compileCommands: T }
export interface ConfigDraft {
  name: string | null
  repoUrl: string | null
  branch: string | null
  /** Each layer with its core (`core`, by name). */
  layers: ArchLayer[]
  cores: DraftCore[]
  /** `clang` / `views` / `docx` sections, carried into the project's build config as they are. */
  settings: Record<string, unknown>
}
export interface ConfigPreview {
  draft: ConfigDraft
  /** Per core: the files the config names that are not in the repository - step 2 asks for them. */
  expectedUploads: Record<string, CoreInputs<string | null>>
  report: ConfigReportItem[]
  repositoryChecked: boolean
}

export interface Project {
  id: string
  name: string
  icon: string
  client: string
  repoPath: string
  defaultBranch: string
  standard: string
  latestVersion: string | null
  inReviewCount: number
  progress: number
  lastRun: string | null
  team: TeamMember[]
  architectureLayers: ArchLayer[]
  buildConfig: ProjectBuildConfig
  userRole: UserRole
  pageState: PageState
}

export interface Version {
  /** Backend version id (e.g. "ver3"). Optional — mock data had none. */
  id?: string
  tag: string
  status: VersionStatus
  description: string
  sha: string
  shortSha: string
  branch: string
  docsCount: number
  date: string
  pageState: PageState
  newCommitsSince?: number
  /** What the run that made this version warned about — a component path the checkout did not
   *  have, a dictionary it ran without (`versions.run_report.warnings`). */
  warnings: string[]
}

export interface Commit {
  sha: string
  shortSha: string
  message: string
  author: string
  relativeTime: string
  branch: string
  versionTag?: string
  pageState: PageState
}

export interface Document {
  id: string
  name: string
  process: string
  status: DocStatus
  assignee?: string
  version: string
  updatedAt: string
  subtitle?: string
  layer?: string
  group?: string
  due?: string
  assigneeInitials?: string
  assigneeColor?: string
  assigneeTextColor?: string
}

/** Per-section review outcome (null = not yet reviewed). */
export type SectionReviewState = 'accepted' | 'declined' | 'edited'

/** One section of a document's detail body (richtext or a markdown table). */
export interface DocSection {
  key: string
  title: string
  order: number
  content: string
  reviewState: SectionReviewState | null
  reviewedBy?: string | null
  reviewedAt?: string | null
}

/** A single document with its full section body — for the inspector view. */
export interface DocumentDetail extends Document {
  sections: DocSection[]
  reviewProgress?: { resolved: number; total: number }
}

/* ── Rich render payload (GET …/documents/{id}/render) — the DOCX-like view ── */

export type RichSectionType = 'richtext' | 'table' | 'diagram' | 'flowchart_table' | 'behavior_table' | 'test_spec'

/** One SWE.4 test spec (a function, or a Dynamic Behaviour interaction): the DOCX's Table A + B. */
export interface TestSpecData {
  testCaseId: string
  generationMethod: string
  returnType: string
  equipment: string
  platform: string
  priority: string
  environment: string
  precondition: { mocks: string[]; parameters: string[]; globals: string[] }
  inputs: string[]
  /** Numbered as the control flow nests: "2", "2.a", "2.b.1". Empty when no CFG. */
  steps: { number: string; text: string }[]
  /** Each expected result with the step(s) that produce it. */
  expected: { text: string; steps: string[] }[]
  /** What the DOCX prints when there is nothing to assert. */
  expectedNote: string | null
}

/** Counts the SWE.4 page shows under its title. */
export interface TestSummary {
  units: number
  functionSpecs: number
  dynamicSpecs: number
  mocks: number
  equipment: string
  platform: string
}

export interface RichTable {
  headers: string[]
  rows: string[][]
}

export interface FlowchartEntry {
  imageUrl: string | null
  mermaid: string | null
  label: string
}

export interface FlowchartTableData {
  description: string
  flowcharts: FlowchartEntry[]
  risk: string
  capacity: string
  inputName: string
  outputName: string
}

export interface BehaviorTableData {
  descriptionList: string[]
  risk: string
  capacity: string
  inputName: string
  outputName: string
  diagramUrl: string | null
}

/** One node of the rendered document tree (sections nest via `children`). */
export interface RichSection {
  id: string
  number: string
  title: string
  level: number
  type: RichSectionType
  content: string | null
  table: RichTable | null
  /** Absolute URL of the rendered diagram PNG (for `type: 'diagram'`). */
  imageUrl: string | null
  /** Mermaid source for the diagram, when the upstream `.mmd` exists. */
  mermaid: string | null
  children: RichSection[]
  flowchartTable?: FlowchartTableData | null
  behaviorTable?: BehaviorTableData | null
  testSpec?: TestSpecData | null
}

export interface DocCover {
  projectName: string
  subtitle: string
  version: string
  layer: string
  group: string
  standard?: string
  process?: string
  generatedAt?: string
}

export interface TocEntry {
  id: string
  number: string
  title: string
  level: number
}

export interface DocMeta {
  pipelineDataAvailable: boolean
  modelDataAvailable: boolean
  source: 'pipeline' | 'model'
  layers: string[]
  components: string[]
  unitsTotal: number
  functionsTotal: number
  globalsTotal: number
}

/** Full rendered document — cover page, TOC, typed/nested sections, meta. */
export interface RichDocument {
  cover: DocCover
  toc: TocEntry[]
  sections: RichSection[]
  meta: DocMeta
  /** SWE.4 only. */
  testSummary?: TestSummary | null
}

/** KPI counts for a project's documents (mapped from GET …/documents/stats). */
export interface DocStats {
  total: number
  approved: number
  inReview: number
  never: number
  unchanged: number
}

/* ── Analysis jobs ─────────────────────────────────────────────────── */

export type JobStatus = 'queued' | 'running' | 'paused' | 'complete' | 'failed' | 'cancelled'
export type JobPhaseStatus = 'pending' | 'running' | 'done' | 'failed'

export interface JobPhase {
  number: number
  name: string
  status: JobPhaseStatus
  durationSeconds: number | null
}

export interface AnalysisJob {
  id: string
  status: JobStatus
  phase: number
  phasePct: number
  currentActivity: string
  activityDetail: string
  elapsedSeconds: number
  etaSeconds: number | null
  phases: JobPhase[]
  commitSha: string
  shortSha: string
  branch: string
  versionId: string | null
  versionTag: string | null
  startedAt: string | null
  completedAt: string | null
  errorMessage: string | null
}

/** A function discovered after Phase 1, for the visibility editor. */
export interface AnalysisFunction {
  id: string
  name: string
  filePath: string
  layer: string
  group: string
  isVisible: boolean
  isNew: boolean
  description: string
  /** Enclosing class/struct, namespaces dropped. Empty for free functions. */
  className: string
}

export interface JobFunctions {
  functions: AnalysisFunction[]
  summary: { total: number; hidden: number; newSinceLast: number }
}

/* ── Notifications ─────────────────────────────────────────────────── */

export interface AppNotification {
  id: string
  projectId: string
  type: string
  message: string
  readAt: string | null
  createdAt: string
  relativeTime: string
}

/* ── Compare ───────────────────────────────────────────────────────── */

export type DiffType = 'added' | 'changed' | 'removed' | 'unchanged'

export interface CompareRef {
  ref: string
  version: string | null
  branch: string
}

export interface CompareSummary {
  added: number
  changed: number
  removed: number
  unchanged: number
}

export interface CompareChangedDoc {
  documentId: string
  name: string
  process: string
  diffType: DiffType
  sectionsChanged: string[]
}

export interface CompareResult {
  current: CompareRef
  baseline: CompareRef
  summary: CompareSummary
  changedDocuments: CompareChangedDoc[]
}

export interface CompareSectionDiff {
  key: string
  title: string
  diffType: DiffType
  currentContent: string
  baselineContent: string
}

export interface CompareDocumentDetail {
  documentName: string
  sections: CompareSectionDiff[]
}

/* ── Rich, highlight-annotated compare diff (GET …/compare/documents/{id}) ── */

/** Inline change mark on a piece of content. */
export type DiffMark = 'none' | 'add' | 'del' | 'change'

/** A run of text carrying one change mark (word-level highlight). */
export interface DiffSegment {
  text: string
  mark: DiffMark
}

export interface CompareTextBlock {
  kind: 'text'
  segments: DiffSegment[]
}

export interface CompareKeyValueBlock {
  kind: 'keyvalue'
  label: string
  segments: DiffSegment[]
}

export interface CompareTableBlock {
  kind: 'table'
  headers: string[]
  rows: string[][]
  /** Per-row mark, parallel to `rows`. */
  rowMarks: DiffMark[]
  /** Per-cell mark, parallel to `rows[i]`. */
  cellMarks: DiffMark[][]
}

export interface CompareDiagramBlock {
  kind: 'diagram'
  imageUrl: string | null
  mermaid: string | null
  caption: string | null
  changed: boolean
}

export type CompareBlock =
  | CompareTextBlock
  | CompareKeyValueBlock
  | CompareTableBlock
  | CompareDiagramBlock

/** Where a section's data came from + which side(s) carry it. */
export interface CompareSource {
  artifact: string
  present: 'both' | 'current' | 'baseline'
}

/** One diffed section rendered for both the reference and current panes. */
export interface CompareRichSection {
  id: string
  number: string
  title: string
  level: number
  diffType: DiffType
  source: CompareSource
  currentBlocks: CompareBlock[]
  baselineBlocks: CompareBlock[]
}

export interface CompareDiffRefInfo {
  ref: string | null
  version: string | null
  branch: string | null
  shortSha: string | null
  hasSnapshot: boolean
}

/**
 * The compare-document-detail payload. `mode: 'rich'` carries the full
 * highlight-annotated render (descriptions, tables, mermaid); `mode: 'flat'` is
 * the legacy interface-table fallback (markdown strings in `flatSections`).
 */
export interface CompareDocumentDiff {
  mode: 'rich' | 'flat'
  documentName: string
  current?: CompareDiffRefInfo
  baseline?: CompareDiffRefInfo
  summary?: CompareSummary
  sections: CompareRichSection[]
  flatSections: CompareSectionDiff[]
}
