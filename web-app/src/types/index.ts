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

/** A document's review state (docs/spec/REVIEW_APPROVE_API_SPEC.md §1). One label each, everywhere:
 *  In review · Ready for approval · Changes requested · Approved (lib/reviewStatus.ts). */
export type ReviewStatus = 'in_review' | 'submitted' | 'changes_requested' | 'approved'
export type DocStatus = ReviewStatus
/** A version's status is derived from its documents (approved when every one is); `draft` = no
 *  documents yet (its run is going, or it was only tagged). */
export type VersionStatus = 'in_review' | 'approved' | 'draft'
/** `complete` = the version on screen is approved. */
export type PageState = 'never' | 'running' | 'in_review' | 'complete' | 'stale'

/** Staged generation: a version's model covers whole layers, its documents are made per component,
 *  by any number of runs (`GET …/versions/{vid}/components`). `stopped` = it was waiting or being
 *  made when its run died; `stale` = it has documents, but a layer added to the model since
 *  changed what they say (a re-export makes them again); `not_requested` = nobody asked for it yet. */
export type ComponentState =
  'generated' | 'generating' | 'waiting' | 'stopped' | 'failed' | 'stale' | 'not_requested'

export interface VersionComponent {
  /** Its output folder (`Layer1.Math`) — what `documents.group` and the generate call name. */
  id: string
  layer: string
  name: string
  state: ComponentState
  /** Of this version's model; a document outside it (an old group run) cannot be made again here. */
  inModel: boolean
  /** Its layer is in the model. false: named by the version's config in a layer the model lacks
   *  yet — Generate adds that layer (parse + descriptions) before making its documents. */
  layerParsed: boolean
  error: string | null
  documents: { id: string; process: string; status: ReviewStatus }[]
}

/** The version's latest writing run (generate / export / reexport / resume / web job). */
export interface VersionRun {
  command: string
  /** Holds the version now; null = this server cannot tell (no Postgres). */
  alive: boolean | null
  /** Recorded as running, but its process is gone: cut short — `analyzer.py resume` continues it. */
  stopped: boolean
  outcome: string
  host: string | null
  startedAt: string | null
  finishedAt: string | null
  stage: string | null
  done: number | null
  total: number | null
  stageStartedAt: string | null
  progressAt: string | null
}

/** A run at work on one of the project's versions now, or cut short — whichever front door
 *  started it (`GET /projects/{pid}/runs`). */
export interface ProjectRun extends VersionRun {
  versionId: string
  versionTag: string
}

/** The web job at work on the version now (queued or running): what Stop cancels. `mode`
 *  `export` / `reexport` = documents into this version; anything else = the version's own run. */
export interface VersionJob {
  id: string
  mode: string
  status: string
}

export interface VersionComponents {
  components: VersionComponent[]
  counts: Partial<Record<ComponentState, number>>
  run: VersionRun | null
  /** null from an API that does not say (older), or when no web job is at work on it. */
  job: VersionJob | null
}

/** A person as the review routes name them. */
export interface UserRef {
  userId: string
  name: string
  initials: string
}

export type ReviewEventKind =
  | 'generated' | 'carried' | 'assigned' | 'unassigned' | 'claimed'
  | 'submitted' | 'approved' | 'changes_requested' | 'reopened'

/** One step of a document's review record (A10, A11). */
export interface ReviewEvent {
  id: string
  documentId: string
  versionId: string
  kind: ReviewEventKind
  /** null: the run did it. */
  actor: UserRef | null
  at: string
  comment: string | null
  payload: Record<string, unknown>
  /** A11 only: the document the event is about. */
  document?: { id: string; name: string; process: string }
}

/** A document's review: the comments, the approval, where the approval came from. */
export interface DocReview {
  /** The reviewer's comment at the last submit. */
  comment: string | null
  /** The admin's comment at the last request for changes (cleared by the next submit). */
  changesComment: string | null
  approvedBy: UserRef | null
  approvedAt: string | null
  approvalComment: string | null
  /** SHA-256 of the Word file that was approved. */
  docxSha256: string | null
  /** The earlier version the approval was carried from (its content was the same). */
  carriedFrom: { versionId: string; tag: string } | null
  lastEvent: ReviewEvent | null
}

/** A version's review counts (A14). */
export interface VersionReview {
  documents: number
  approved: number
  inReview: number
  submitted: number
  changesRequested: number
  carried: number
  /** The last approval, set only when the version is approved. */
  approvedBy: UserRef | null
  approvedAt: string | null
}

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
  /** Per core: the path the config names for each of its files, as written ('/' separators). The
   *  files are the user's own inputs: step 2 asks for each by name, and a picked folder fills them. */
  expectedUploads: Record<string, CoreInputs<string | null>>
  report: ConfigReportItem[]
  repositoryChecked: boolean
}

/** A folder on the server ArtiFex runs on (GET /repositories/local-folders): `git` when it is a
 *  git repository (holds `.git`). Paths use forward slashes. */
export interface LocalFolder { name: string; path: string; git: boolean }
/** One folder's subfolders. `path` '' is the top list (the server's drives or `/`, or the folders
 *  it limits the picker to - `limited`), whose `parent` is null; a `parent` of '' goes back to it.
 *  `truncated`: the server listed only the first folders. */
export interface LocalFolders {
  path: string
  parent: string | null
  folders: LocalFolder[]
  limited: boolean
  truncated: boolean
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
  /** Its documents' review counts; null from an API that does not send them. */
  review: VersionReview | null
  /** How it was made; null from an API that does not say. */
  run: VersionRunInfo | null
}

/** How a version was made (`versions.run_report`): from the web app or the command line, for
 *  which scope, which documents, or the model only. */
export interface VersionRunInfo {
  madeBy: 'web' | 'cli' | null
  /** `type`: project | layer | group | component. */
  scope: { type: string; names: string[] } | null
  docType: 'swe3' | 'swe4' | 'all' | null
  modelOnly: boolean
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
  /** Display label: the version's tag when known, else its id. */
  version: string
  /** The version the document belongs to (its id), whatever the Subbar shows. */
  versionId?: string
  updatedAt: string
  subtitle?: string
  layer?: string
  group?: string
  /** The one reviewer, or null: "Needs a reviewer". */
  reviewer: UserRef | null
  review: DocReview
  /** The reviewer's name, initials and avatar colours (null reviewer → undefined). */
  assignee?: string
  assigneeInitials?: string
  assigneeColor?: string
  assigneeTextColor?: string
}

/** `GET …/documents/{id}`: the same shape as a list row. */
export type DocumentDetail = Document

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

/* ── Review & update: texts a reviewer can correct ── */

export type SlotKind =
  | 'description' | 'inputName' | 'outputName' | 'behaviourDescription'
  | 'unitDescription' | 'structDescription' | 'nodeLabel'

/** One correctable text, in the shape every review route returns it (API spec §5 `Slot`), and
 *  the render payload carries beside each text. The key is the server's: send it back as is. */
export interface Slot {
  kind: SlotKind
  key: string
  /** What the document prints for this slot now ('' when empty: the page shows a stand-in). */
  text: string
  /** The LLM's wording (the original a correction replaced); null when the LLM wrote nothing. */
  llmText: string | null
  /** The reviewer's words; null when never corrected. */
  humanText: string | null
  /** A correction is in force (the document prints `humanText`). */
  isOverridden: boolean
  /** A correction exists but its code changed: kept, not printed. */
  isOrphaned: boolean
  /** Undo would change the text. Offer Undo exactly when true. */
  canUndo: boolean
  /** A user id. */
  updatedBy: string | null
  updatedAt: string | null
  /** Behaviour rows: the bullets of `text`, and the row's two function ids. */
  bullets?: string[]
  functionId?: string
  externalCallerId?: string
  /** Node labels: the flowchart and the node. */
  flowchartId?: string
  nodeId?: string
}

/** A text a correction made out of date: the next run rewrites it (API spec §5 `QueuedSlot`).
 *  `label` only when the server names it — the key is never taken apart here. */
export interface QueuedSlot {
  slotKind: string
  slotKey: string
  label?: string
}

/** A save's answer: the slot as it now is, plus what it replaced and what it queued. */
export interface SlotSaveResult extends Slot {
  previousText: string | null
  firstEdit: boolean
  queuedForRegeneration: QueuedSlot[]
}

/** R10: one text the next run rewrites, because a correction it was written from changed. */
export interface QueuedRegeneration extends QueuedSlot {
  /** Plain language, from the server. */
  reason: string
  /** The correction that made it out of date. */
  causedBy: QueuedSlot | null
  requestedAt: string | null
}

export interface SlotHistoryEntry {
  seq: number
  humanText: string
  updatedBy: string | null
  updatedAt: string | null
}

/** R7: one flowchart's node labels. */
export interface FlowchartLabels {
  flowchartId: string
  functionName: string
  labels: Slot[]
  graphAvailable: boolean
  note: string | null
  /** The chart as Graphviz DOT: its arrows give the boxes their order. */
  dot: string
}

/** R9: whether the version's Word files have every correction, and its latest re-export. */
export interface ExportReadiness {
  stale: boolean
  /** The components (documents' `group`) whose Word files are behind, when the version is —
   *  the version-wide question only. Absent: an API that does not say which. */
  staleComponents?: string[]
  explanation: string | null
  overrideCount: number
  pendingRenders: number
  failedRenders: number
  /** When the version's oldest derived output was written (null: an older API, or none yet). */
  oldestDerivationAt?: string | null
  reexport: {
    jobId: string
    status: string
    startedAt: string | null
    completedAt: string | null
    errorMessage: string | null
  } | null
}

export interface RichTable {
  headers: string[]
  rows: string[][]
  /** Per cell: the slot of a correctable cell, else null (same shape as `rows`). */
  cellSlots?: (Slot | null)[][]
}

/** Whether a flowchart has a picture: `too_large` is over the engine's box limit, `missing`
 *  was not drawn for this run (an older run, or drawing failed). */
export type FlowchartStatus = 'drawn' | 'too_large' | 'missing'

/** One flowchart in a function's table: an SVG the engine draws on every run. */
export interface FlowchartEntry {
  /** The function's signature. */
  label: string
  status: FlowchartStatus
  /** The SVG, when drawn. */
  imageUrl: string | null
  /** Natural size in CSS px, when known: the page reserves it before the image loads. */
  width: number | null
  height: number | null
  /** Boxes in the chart (0 when the API did not say). */
  boxes: number
  /** The chart's id for the label editor (R7/R8); null for an older render. */
  flowchartId: string | null
  /** It has a stored graph whose labels a reviewer can correct. */
  editable: boolean
}

export interface FlowchartTableData {
  description: string
  flowcharts: FlowchartEntry[]
  risk: string
  capacity: string
  inputName: string
  outputName: string
  descriptionSlot: Slot | null
  inputNameSlot: Slot | null
  outputNameSlot: Slot | null
}

export interface BehaviorTableData {
  descriptionList: string[]
  risk: string
  capacity: string
  inputName: string
  outputName: string
  diagramUrl: string | null
  descriptionSlot: Slot | null
  inputNameSlot: Slot | null
  outputNameSlot: Slot | null
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
  /** A function section without a flowchart: the slot of its `content` (its description). */
  contentSlot?: Slot | null
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

/** Counts per review state (GET …/documents/stats, A13). */
export interface DocStats {
  total: number
  inReview: number
  submitted: number
  changesRequested: number
  approved: number
  needsReviewer: number
  carried: number
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
  /** The version the run makes or adds to. A cancelled generation stops naming it once the
   *  server has deleted the draft. */
  versionId: string | null
  versionTag: string | null
  /** `export` / `reexport` add documents to a version; anything else is the version's own run. */
  mode: string
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
  /** The document it is about, when it is about one: a click opens it. */
  documentId: string | null
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
