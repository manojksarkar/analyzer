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
export interface ArchLayer { name: string; path?: string; libPaths?: string[]; groups: ArchGroup[] }

/** Build configuration summary surfaced on the overview (token-free). */
export interface ProjectBuildConfig {
  definitions?: { mode: string; count: number; fileName?: string }
  dataDictionary?: string
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

export type RichSectionType = 'richtext' | 'table' | 'diagram' | 'flowchart_table' | 'behavior_table'

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
