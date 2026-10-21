"""
Abstract repository interfaces.

Every concrete database adapter (in-memory, SQLite, Postgres, …) must
implement these ABCs.  The rest of the application depends only on these
interfaces, making the storage layer trivially swappable.

Usage:
    from api.repositories.interfaces import IUserRepository, IProjectRepository, ...
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional
from ..models.domain import (
    User, Project, ProjectMember, Version, Commit, AnalysisJob,
    Document, DocumentSection, DocumentAssignment, Function,
    CompareResult, DocumentDiff, Notification, AccessRequest, ReviewEvent, JobEvent,
)


class IUserRepository(ABC):
    @abstractmethod
    def get_by_id(self, user_id: str) -> Optional[User]: ...

    @abstractmethod
    def get_by_email(self, email: str) -> Optional[User]: ...

    @abstractmethod
    def create(self, user: User) -> User: ...

    @abstractmethod
    def update(self, user: User) -> User: ...

    @abstractmethod
    def list_by_ids(self, ids: list[str]) -> list[User]: ...

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> list[User]: ...


class IProjectRepository(ABC):
    @abstractmethod
    def list_for_user(self, user_id: str) -> list[Project]: ...

    @abstractmethod
    def list_all(self) -> list[Project]:
        """Every project, membership ignored. For a superuser listing, and nothing else."""

    @abstractmethod
    def get(self, project_id: str) -> Optional[Project]: ...

    @abstractmethod
    def create(self, project: Project) -> Project: ...

    @abstractmethod
    def update(self, project: Project) -> Project: ...

    @abstractmethod
    def delete(self, project_id: str) -> None: ...

    @abstractmethod
    def search(self, query: str) -> list[Project]: ...


class IProjectMemberRepository(ABC):
    @abstractmethod
    def list_members(self, project_id: str) -> list[ProjectMember]: ...

    @abstractmethod
    def get_member(self, project_id: str, user_id: str) -> Optional[ProjectMember]: ...

    @abstractmethod
    def add_member(self, member: ProjectMember) -> ProjectMember: ...

    @abstractmethod
    def update_member(self, member: ProjectMember) -> ProjectMember: ...

    @abstractmethod
    def remove_member(self, project_id: str, user_id: str) -> None: ...

    @abstractmethod
    def list_pending(self, project_id: str) -> list[ProjectMember]: ...

    @abstractmethod
    def cancel_invite(self, project_id: str, invite_id: str) -> None: ...


class IAccessRequestRepository(ABC):
    @abstractmethod
    def create(self, req: AccessRequest) -> AccessRequest: ...

    @abstractmethod
    def list_pending(self, project_id: str) -> list[AccessRequest]: ...

    @abstractmethod
    def get(self, req_id: str) -> Optional[AccessRequest]: ...

    @abstractmethod
    def update(self, req: AccessRequest) -> AccessRequest: ...


class IVersionRepository(ABC):
    @abstractmethod
    def list_for_project(self, project_id: str) -> list[Version]: ...

    @abstractmethod
    def get(self, version_id: str) -> Optional[Version]: ...

    @abstractmethod
    def create(self, version: Version) -> Version: ...

    @abstractmethod
    def update(self, version: Version) -> Version: ...

    @abstractmethod
    def delete(self, version_id: str) -> None: ...

    @abstractmethod
    def get_by_tag(self, project_id: str, tag: str) -> Optional[Version]: ...


class ICommitRepository(ABC):
    @abstractmethod
    def list_for_project(
        self, project_id: str, page: int = 1, per_page: int = 20
    ) -> tuple[list[Commit], int]: ...

    @abstractmethod
    def get(self, project_id: str, sha: str) -> Optional[Commit]: ...

    @abstractmethod
    def upsert(self, commit: Commit) -> Commit: ...


class IAnalysisJobRepository(ABC):
    @abstractmethod
    def create(self, job: AnalysisJob) -> AnalysisJob: ...

    @abstractmethod
    def get(self, job_id: str) -> Optional[AnalysisJob]: ...

    @abstractmethod
    def get_current(self, project_id: str) -> Optional[AnalysisJob]:
        """The project's latest non-cancelled GENERATION job. Re-exports are never current."""

    @abstractmethod
    def list_for_version(self, version_id: str) -> list[AnalysisJob]:
        """Every job for a version, newest first: its generation, and any re-exports."""

    @abstractmethod
    def list_active(self) -> list[AnalysisJob]:
        """Every job, of every project, still marked queued, running or paused."""

    @abstractmethod
    def update(self, job: AnalysisJob) -> AnalysisJob:
        """Write the job's progress and description -- never its state (`JOB_STATE_FIELDS`), and
        nothing at all once it is cancelled, removed or interrupted (`JOB_CLOSED_STATUSES`). The
        job may be a copy read a moment earlier: what changed since in its state stays."""

    @abstractmethod
    def transition(self, job_id: str, from_status: Iterable[str], to_status: str,
                   **values: Any) -> bool:
        """Change the job's status to `to_status`, and its fields to `values`, only if its status
        is one of `from_status` now -- one statement, so nothing can change it in between. False
        when it was not: someone else changed it first (a cancel, the run's end), and the caller
        acts on what it is now."""

    # -- the queue (docs/design/JOB_SCHEDULING_DESIGN.md §4, §5) --------------------------------
    @abstractmethod
    def add_to_lane(self, job: AnalysisJob, decide: Any) -> Any:
        """Insert `job` unless `decide(jobs)` says otherwise -- `jobs`, the project's jobs held,
        queued, running or paused, read under the project's lock, so two submits at once count
        each other. `decide` raises to refuse, returns a value to answer instead (nothing
        inserted), or None: the job is inserted, in the same transaction. Returns that value."""

    @abstractmethod
    def lane_jobs(self, project_id: str, statuses: Iterable[str]) -> list[AnalysisJob]:
        """The project's jobs in `statuses`, oldest place first."""

    @abstractmethod
    def in_status(self, statuses: Iterable[str]) -> list[AnalysisJob]:
        """Every project's jobs in `statuses`, oldest place first."""

    @abstractmethod
    def find_by_request_key(self, project_id: str, key: str) -> Optional[AnalysisJob]: ...

    @abstractmethod
    def recent_ended(self, project_id: str, limit: int = 50) -> list[AnalysisJob]:
        """The project's ended jobs, the last ended first."""

    @abstractmethod
    def claim(self, job_id: str, from_status: str, *, cap: Optional[int], runner: str,
              now: Any, **values: Any) -> bool:
        """Start the job -- `running`, its alive signal and `runner` set, `started_at` kept when it
        has one -- only if, read in one transaction under the queue's lock: it is `from_status`;
        no other job is running or paused in its project lane, or on its version; and, `cap`
        given, fewer than `cap` generations run. False otherwise (REQ-JS-15)."""

    @abstractmethod
    def record_run(self, job: AnalysisJob, decide: Any) -> Any:
        """Insert `job` -- a command-line run, `running` already -- unless `decide(lane_jobs,
        generations_running)` answers otherwise. Read in one transaction under the queue's lock
        and the project's: `lane_jobs`, the project's jobs of the job's lane held, queued, running
        or paused; `generations_running`, every project's running generations. `decide` returns
        None (the job is inserted) or a refusal, returned with nothing written. A run that loses
        to a claim on the lane's unique index is refused as `("busy", [])`; a project with no row
        as `("no_project", [])` (REQ-JS-28, 29)."""

    @abstractmethod
    def prune_ended(self, before: Any) -> int:
        """Remove the jobs that ended before `before`, with their events and registered functions
        -- but each existing version's newest generation job, which an update reads how the
        version was made from (REQ-JS-34). Returns how many."""


class IDocumentRepository(ABC):
    @abstractmethod
    def list_for_project(
        self,
        project_id: str,
        version_id: Optional[str] = None,
        process: Optional[str] = None,
        status: Optional[str] = None,
        assignee_id: Optional[str] = None,
        query: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[Document], int]:
        """`assignee_id` is a user id -- the documents that user reviews -- or `"none"`: the
        documents with no reviewer."""

    @abstractmethod
    def get(self, document_id: str) -> Optional[Document]: ...

    @abstractmethod
    def update(self, document: Document) -> Document: ...

    @abstractmethod
    def get_stats(self, project_id: str, version_id: Optional[str] = None) -> dict:
        """`total`, one count per review state, `needs_reviewer` (not approved, no reviewer) and
        `carried` (approved by carrying an unchanged document's approval forward)."""

    @abstractmethod
    def list_sections(self, document_id: str) -> list[DocumentSection]: ...

    @abstractmethod
    def get_section(self, document_id: str, section_key: str) -> Optional[DocumentSection]: ...

    @abstractmethod
    def update_section(self, section: DocumentSection) -> DocumentSection: ...

    @abstractmethod
    def set_word_file_at(self, document_id: str, at) -> None:
        """When the run that wrote the document's working Word file started
        (docs/design/WORD_FILE_UPDATES.md). Written only here: `update` leaves it alone."""


class IDocumentAssignmentRepository(ABC):
    """A document's reviewer. One per document: `set_reviewer` replaces."""

    @abstractmethod
    def list_for_document(self, document_id: str) -> list[DocumentAssignment]: ...

    @abstractmethod
    def assign(self, assignment: DocumentAssignment) -> DocumentAssignment:
        """Make `assignment.user_id` the reviewer -- the same as `set_reviewer`."""

    @abstractmethod
    def set_reviewer(self, assignment: DocumentAssignment) -> Optional[DocumentAssignment]:
        """Replace the document's reviewer; returns the one it replaced, or None."""

    @abstractmethod
    def reviewers(self, document_ids: list[str]) -> dict[str, str]:
        """`{document id: reviewer user id}` for those of `document_ids` that have one."""

    @abstractmethod
    def remove(self, document_id: str, user_id: str) -> None: ...

    @abstractmethod
    def batch_assign(self, assignments: list[DocumentAssignment]) -> None: ...


class IJobEventRepository(ABC):
    """The queue's record: one event per step of a job, or of a project's queue (REQ-JS-33)."""

    @abstractmethod
    def add(self, event: JobEvent) -> JobEvent: ...

    @abstractmethod
    def list_for_job(self, job_id: str) -> list[JobEvent]:
        """Oldest first."""

    @abstractmethod
    def list_for_project(self, project_id: str, limit: int = 100) -> list[JobEvent]:
        """Newest first."""


class IReviewEventRepository(ABC):
    """The review record: one event per step of a document's review."""

    @abstractmethod
    def add(self, event: ReviewEvent) -> ReviewEvent: ...

    @abstractmethod
    def list_for_document(self, document_id: str) -> list[ReviewEvent]:
        """Newest first."""

    @abstractmethod
    def list_for_project(self, project_id: str, version_id: Optional[str] = None,
                         document_id: Optional[str] = None, limit: int = 50) -> list[ReviewEvent]:
        """Newest first."""

    @abstractmethod
    def last_for_documents(self, document_ids: list[str]) -> dict[str, ReviewEvent]:
        """Each document's newest event."""


class IFunctionRepository(ABC):
    @abstractmethod
    def list_for_job(self, job_id: str) -> list[Function]: ...

    @abstractmethod
    def get(self, function_id: str) -> Optional[Function]: ...

    @abstractmethod
    def update(self, function: Function) -> Function: ...

    @abstractmethod
    def bulk_update_visibility(
        self, function_ids: list[str], is_visible: bool, project_id: Optional[str] = None
    ) -> int:
        """Set visibility on those of `function_ids` that belong to `project_id` (all of them when
        it is None); returns how many were updated."""
        ...


class ICompareRepository(ABC):
    @abstractmethod
    def get_or_create(
        self,
        project_id: str,
        current_ref: str,
        baseline_ref: str,
    ) -> CompareResult: ...

    @abstractmethod
    def list_diffs(self, compare_id: str) -> list[DocumentDiff]: ...

    @abstractmethod
    def get_document_diff(
        self, compare_id: str, document_id: str
    ) -> Optional[DocumentDiff]: ...


class INotificationRepository(ABC):
    @abstractmethod
    def list_unread(self, user_id: str) -> list[Notification]: ...

    @abstractmethod
    def list_for_user(self, user_id: str, limit: int = 30) -> list[Notification]:
        """Read and unread, newest first."""

    @abstractmethod
    def get(self, notification_id: str) -> Optional[Notification]: ...

    @abstractmethod
    def mark_read(self, notification_id: str) -> Notification: ...

    @abstractmethod
    def mark_all_read(self, user_id: str) -> None: ...

    @abstractmethod
    def create(self, notification: Notification) -> Notification: ...
