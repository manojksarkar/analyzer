"""
Response schemas for OpenAPI / Swagger documentation.
====================================================

These Pydantic models describe the **exact shape of every response body** so the
Swagger UI (`/docs`) shows a precise schema for each endpoint.

They are attached to routes via the route decorator's ``responses=`` argument,
e.g. ``@router.get("...", responses={200: {"model": ProjectResponse}})`` — NOT
via ``response_model=``. This is deliberate:

* ``responses={...: {"model": X}}`` documents the schema in OpenAPI **without**
  touching the actual returned object at runtime.
* ``response_model=X`` would *filter* the response through the model, dropping any
  field the model omits and adding ``null`` for any optional field a particular
  code path leaves out (e.g. the synthesized render path omits ``image_url`` /
  ``mermaid``). The handlers return plain dicts whose shapes are the source of
  truth and which the web-app depends on, so we document them but never mutate
  them.

Date/time fields are typed ``str`` because the route helpers already emit ISO-8601
strings (``.isoformat()``). Genuinely free-form blobs (``build_config``,
``architecture_layers``, repo ``entries``) are typed loosely on purpose.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Shared / generic
# ---------------------------------------------------------------------------

class MessageResponse(BaseModel):
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    status: int


class ErrorResponse(BaseModel):
    """Standard error envelope returned by every endpoint on failure."""
    error: ErrorBody


class Pagination(BaseModel):
    page: int
    per_page: int
    total: int


class DocCounts(BaseModel):
    total: int
    approved: int
    in_review: int
    never: int
    unchanged: int


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class UserView(BaseModel):
    id: str
    name: str
    email: str
    initials: str
    avatar_url: Optional[str] = None
    created_at: str


class SignInResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: UserView


class RefreshResponse(BaseModel):
    access_token: str


class MeResponse(BaseModel):
    user: UserView


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------

class ProjectView(BaseModel):
    id: str
    name: str
    client: str
    compliance_standard: str
    status: str
    last_run_at: Optional[str] = None
    current_version: Optional[str] = None
    doc_counts: DocCounts
    team_count: int
    my_role: Optional[str] = None
    repo_url: str
    default_branch: str
    build_config: Dict[str, Any]
    architecture_layers: List[Dict[str, Any]]
    created_at: str
    updated_at: str


class ProjectResponse(BaseModel):
    project: ProjectView


class ProjectListResponse(BaseModel):
    projects: List[ProjectView]


class ProjectSearchItem(BaseModel):
    id: str
    name: str
    client: str


class ProjectSearchResponse(BaseModel):
    projects: List[ProjectSearchItem]


class AccessRequestView(BaseModel):
    id: str
    status: str


class AccessRequestResponse(BaseModel):
    request: AccessRequestView


class AccessRequestListItem(BaseModel):
    id: str
    user_id: str
    requested_at: str


class AccessRequestListResponse(BaseModel):
    requests: List[AccessRequestListItem]


# ---------------------------------------------------------------------------
# Commits & Versions
# ---------------------------------------------------------------------------

class CommitView(BaseModel):
    sha: str
    message: str
    author: str
    committed_at: str
    branch: str
    doc_status: str
    version: Optional[str] = None
    is_current: bool


class CommitListResponse(BaseModel):
    commits: List[CommitView]
    pagination: Pagination


class VersionView(BaseModel):
    id: str
    tag: str
    commit_sha: str
    branch: str
    description: str
    status: str
    docs_count: int
    created_by: str
    created_at: str


class VersionResponse(BaseModel):
    version: VersionView


class VersionListResponse(BaseModel):
    versions: List[VersionView]


# ---------------------------------------------------------------------------
# Jobs & Functions
# ---------------------------------------------------------------------------

class PhaseView(BaseModel):
    number: int
    name: str
    status: str
    duration_seconds: Optional[float] = None


class JobView(BaseModel):
    id: str
    status: str
    phase: int
    phase_pct: int
    current_activity: str
    activity_detail: str
    elapsed_seconds: int
    eta_seconds: Optional[int] = None
    phases: List[PhaseView]
    commit_sha: str
    branch: str
    version_id: Optional[str] = None
    version_tag: Optional[str] = None
    started_at: str
    completed_at: Optional[str] = None
    error_message: Optional[str] = None


class StartJobResponse(BaseModel):
    job_id: str
    status: str


class JobResponse(BaseModel):
    job: JobView


class CurrentJobResponse(BaseModel):
    job: Optional[JobView] = None


class ReexportResponse(BaseModel):
    message: str
    job_id: str


class FunctionView(BaseModel):
    id: str
    name: str
    file_path: str
    layer: str
    group: str
    is_visible: bool
    is_new: bool
    description: Optional[str] = None


class FunctionSummary(BaseModel):
    total: int
    hidden: int
    new_since_last: int


class FunctionListResponse(BaseModel):
    functions: List[FunctionView]
    summary: FunctionSummary


class FunctionVisibilityView(BaseModel):
    id: str
    name: str
    is_visible: bool


class FunctionVisibilityResponse(BaseModel):
    function: FunctionVisibilityView


class BulkUpdateResponse(BaseModel):
    updated_count: int


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------

class AssigneeView(BaseModel):
    user_id: str
    name: str
    initials: str


class SectionView(BaseModel):
    key: str
    title: str
    order: int
    content: str
    review_state: str
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None


class ReviewProgress(BaseModel):
    resolved: int
    total: int


class DocumentView(BaseModel):
    id: str
    name: str
    subtitle: Optional[str] = None
    process: str
    layer: Optional[str] = None
    group: Optional[str] = None
    status: str
    version_id: Optional[str] = None
    due_date: Optional[str] = None
    assignees: List[AssigneeView]
    created_at: str
    updated_at: str


class DocumentDetail(DocumentView):
    sections: List[SectionView]
    review_progress: ReviewProgress


class DocumentResponse(BaseModel):
    document: DocumentView


class DocumentDetailResponse(BaseModel):
    document: DocumentDetail


class DocumentListResponse(BaseModel):
    documents: List[DocumentView]
    pagination: Pagination


class DocStatsResponse(BaseModel):
    stats: DocCounts


class AssigneesResponse(BaseModel):
    assignees: List[AssigneeView]


class SectionReviewView(BaseModel):
    key: str
    review_state: str
    reviewed_by: Optional[str] = None


class SectionReviewResponse(BaseModel):
    section: SectionReviewView


class SubmitReviewResponse(BaseModel):
    message: str
    document_id: str


class DocStatusResponse(BaseModel):
    document_id: str
    status: str


class ApproveAllResponse(BaseModel):
    approved_count: int
    document_ids: List[str]


class ExportAllResponse(BaseModel):
    download_url: str
    expires_at: str


# ----- rich render payload (cover / toc / typed-nested sections / meta) -----

class TableData(BaseModel):
    headers: List[str]
    rows: List[List[str]]


class TocEntry(BaseModel):
    id: str
    number: str
    title: str
    level: int


class RenderSection(BaseModel):
    id: str
    number: str
    title: str
    level: int
    type: str                              # "richtext" | "table" | "diagram"
    content: Optional[str] = None
    table: Optional[TableData] = None
    # Present only on fixture-backed ("pipeline") diagram sections:
    image_url: Optional[str] = None
    mermaid: Optional[str] = None
    children: List["RenderSection"] = []


class RenderCover(BaseModel):
    project_name: str
    subtitle: str
    version: Optional[str] = None
    layer: Optional[str] = None
    group: Optional[str] = None
    standard: str
    process: str
    generated_at: str


class RenderMeta(BaseModel):
    pipeline_data_available: bool
    model_data_available: bool
    source: str                            # "pipeline" | "model"
    layers: List[str]
    components: List[str]
    units_total: int
    functions_total: int
    globals_total: int


class RenderDocument(BaseModel):
    cover: RenderCover
    toc: List[TocEntry]
    sections: List[RenderSection]
    meta: RenderMeta


class RenderResponse(BaseModel):
    document: RenderDocument


# ---------------------------------------------------------------------------
# Team
# ---------------------------------------------------------------------------

class MemberView(BaseModel):
    id: str
    user_id: str
    name: str
    email: str
    initials: str
    role: str
    status: str
    joined_at: Optional[str] = None


class MemberResponse(BaseModel):
    member: MemberView


class MemberListResponse(BaseModel):
    members: List[MemberView]


class PendingListResponse(BaseModel):
    pending: List[MemberView]


class InviteView(BaseModel):
    id: str
    email: str
    role: str
    status: str


class InviteResponse(BaseModel):
    invite: InviteView


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------

class RefView(BaseModel):
    ref: str
    version: Optional[str] = None
    branch: str


class ChangedDocument(BaseModel):
    document_id: str
    name: str
    process: str
    diff_type: str
    sections_changed: List[str]


class CompareResponse(BaseModel):
    current: RefView
    baseline: RefView
    summary: Dict[str, Any]
    changed_documents: List[ChangedDocument]


class CompareDocumentsResponse(BaseModel):
    documents: List[ChangedDocument]
    summary: Dict[str, Any]


class SectionDiff(BaseModel):
    key: str
    title: str
    diff_type: str
    current_content: str
    baseline_content: str


class CompareDocumentDetailResponse(BaseModel):
    document_name: str
    sections: List[SectionDiff]


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

class NotificationView(BaseModel):
    id: str
    project_id: Optional[str] = None
    type: str
    message: str
    read_at: Optional[str] = None
    created_at: str


class NotificationResponse(BaseModel):
    notification: NotificationView


class NotificationListResponse(BaseModel):
    notifications: List[NotificationView]


# ---------------------------------------------------------------------------
# Repositories (wizard) & Users
# ---------------------------------------------------------------------------

class TestConnectionResponse(BaseModel):
    connected: bool
    default_branch: Optional[str] = None
    branches: List[str]
    message: str


class BrowseResponse(BaseModel):
    repo_url: str
    ref: Optional[str] = None
    path: str
    root_name: str
    # Nested {type, name, path, children?} tree — kept loose on purpose.
    entries: List[Dict[str, Any]]


class UploadResponse(BaseModel):
    id: str
    file_name: str
    size: int
    content_type: Optional[str] = None
    kind: str


class UserSearchItem(BaseModel):
    id: str
    name: str
    email: str
    initials: str


class UserSearchResponse(BaseModel):
    users: List[UserSearchItem]


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------

class HealthResponse(BaseModel):
    status: str
    version: str


class RootResponse(BaseModel):
    name: str
    version: str
    docs: str
    health: str


# Resolve the self-referential RenderSection forward reference.
RenderSection.model_rebuild()
