import { z } from 'zod'
import {
  ApiSignInSchema, ApiUserSchema, ApiProjectSchema, ApiCommitSchema, ApiVersionSchema,
  ApiDocumentSchema, ApiDocumentDetailSchema, ApiRichDocumentSchema, ApiMemberSchema,
  ApiJobSchema, ApiFunctionSchema, ApiNotificationSchema,
} from '../../services/mappers'

/**
 * The response envelopes the web-app reads, as zod schemas derived from the same
 * `Api*` shapes the mappers consume (single source of truth). The API-test runner
 * validates a live API's responses against these, so a backend that
 * drops/renames/retypes a field is caught immediately.
 *
 * Most schemas reuse the mapper schemas. A few snake_case shapes the app reads
 * without a dedicated mapper (`compare`, `users/search`, repository wizard,
 * count/url mutation results) are defined here.
 */

const ApiChangedDocSchema = z.object({
  document_id: z.string(), name: z.string(), process: z.string(),
  diff_type: z.string(), sections_changed: z.array(z.string()),
})

// Flat (legacy) interface-table section.
const ApiCompareSectionSchema = z.object({
  key: z.string(), title: z.string(), diff_type: z.string(),
  current_content: z.string(), baseline_content: z.string(),
})

// Rich, highlight-annotated diff section (mode: 'rich').
const ApiRichDiffSectionSchema = z.object({
  id: z.string(), number: z.string(), title: z.string(), level: z.number(),
  diff_type: z.string(),
  source: z.object({ artifact: z.string(), present: z.string() }).optional(),
  current_blocks: z.array(z.unknown()), baseline_blocks: z.array(z.unknown()),
})

const ApiOrgUserSchema = z.object({
  id: z.string(), name: z.string(), email: z.string(), initials: z.string(),
})

export const Envelopes = {
  // ── auth ──
  signin: ApiSignInSchema,
  refresh: z.object({ access_token: z.string() }),
  me: z.object({ user: ApiUserSchema }),

  // ── projects ──
  projects: z.object({ projects: z.array(ApiProjectSchema) }),
  project: z.object({ project: ApiProjectSchema }),
  projectSearch: z.object({
    projects: z.array(z.object({ id: z.string(), name: z.string(), client: z.string() })),
  }),

  // ── commits / versions ──
  commits: z.object({ commits: z.array(ApiCommitSchema) }),
  versions: z.object({ versions: z.array(ApiVersionSchema) }),
  version: z.object({ version: ApiVersionSchema }),

  // ── documents ──
  documents: z.object({ documents: z.array(ApiDocumentSchema) }),
  docStats: z.object({ stats: z.record(z.string(), z.number()) }),
  document: z.object({ document: ApiDocumentDetailSchema }),
  documentRender: z.object({ document: ApiRichDocumentSchema }),
  approvedCount: z.object({ approved_count: z.number() }),
  downloadUrl: z.object({ download_url: z.string() }),

  // ── team ──
  members: z.object({ members: z.array(ApiMemberSchema) }),
  membersPending: z.object({ pending: z.array(ApiMemberSchema) }),
  member: z.object({ member: ApiMemberSchema }),

  // ── jobs / functions ──
  jobCurrent: z.object({ job: ApiJobSchema.nullable() }),
  job: z.object({ job: ApiJobSchema }),
  jobStart: z.object({ job_id: z.string(), status: z.string() }),
  jobFunctions: z.object({
    functions: z.array(ApiFunctionSchema),
    summary: z.object({ total: z.number(), hidden: z.number(), new_since_last: z.number() }),
  }),
  updatedCount: z.object({ updated_count: z.number() }),

  // ── compare ──
  compareSummary: z.object({
    current: z.unknown(), baseline: z.unknown(), summary: z.unknown(),
    changed_documents: z.array(ApiChangedDocSchema),
  }),
  compareDocuments: z.object({ documents: z.array(ApiChangedDocSchema), summary: z.unknown() }),
  // Detail can be the rich diff (mode: 'rich') or the flat fallback (mode: 'flat').
  compareDetail: z.object({
    document_name: z.string(),
    mode: z.string().optional(),
    sections: z.array(z.union([ApiRichDiffSectionSchema, ApiCompareSectionSchema])),
  }),

  // ── notifications ──
  notifications: z.object({ notifications: z.array(ApiNotificationSchema) }),

  // ── wizard (users / repositories) ──
  usersSearch: z.object({ users: z.array(ApiOrgUserSchema) }),
  repoTest: z.object({
    connected: z.boolean(), default_branch: z.string().nullable(),
    branches: z.array(z.string()), message: z.string(),
  }),
  repoEntries: z.object({ entries: z.array(z.unknown()) }),
  repoUpload: z.object({
    id: z.string(), file_name: z.string(), size: z.number(), kind: z.string(),
  }),
} as const
