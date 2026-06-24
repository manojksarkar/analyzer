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
from typing import Optional
from ..models.domain import (
    User, Project, ProjectMember, Version, Commit, AnalysisJob,
    Document, DocumentSection, DocumentAssignment, Function,
    CompareResult, DocumentDiff, Notification, AccessRequest,
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
    def get_current(self, project_id: str) -> Optional[AnalysisJob]: ...

    @abstractmethod
    def update(self, job: AnalysisJob) -> AnalysisJob: ...


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
    ) -> tuple[list[Document], int]: ...

    @abstractmethod
    def get(self, document_id: str) -> Optional[Document]: ...

    @abstractmethod
    def update(self, document: Document) -> Document: ...

    @abstractmethod
    def get_stats(self, project_id: str, version_id: Optional[str] = None) -> dict: ...

    @abstractmethod
    def list_sections(self, document_id: str) -> list[DocumentSection]: ...

    @abstractmethod
    def get_section(self, document_id: str, section_key: str) -> Optional[DocumentSection]: ...

    @abstractmethod
    def update_section(self, section: DocumentSection) -> DocumentSection: ...


class IDocumentAssignmentRepository(ABC):
    @abstractmethod
    def list_for_document(self, document_id: str) -> list[DocumentAssignment]: ...

    @abstractmethod
    def assign(self, assignment: DocumentAssignment) -> DocumentAssignment: ...

    @abstractmethod
    def remove(self, document_id: str, user_id: str) -> None: ...

    @abstractmethod
    def batch_assign(self, assignments: list[DocumentAssignment]) -> None: ...


class IFunctionRepository(ABC):
    @abstractmethod
    def list_for_job(self, job_id: str) -> list[Function]: ...

    @abstractmethod
    def get(self, function_id: str) -> Optional[Function]: ...

    @abstractmethod
    def update(self, function: Function) -> Function: ...

    @abstractmethod
    def bulk_update_visibility(
        self, function_ids: list[str], is_visible: bool
    ) -> None: ...


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
    def mark_read(self, notification_id: str) -> Notification: ...

    @abstractmethod
    def mark_all_read(self, user_id: str) -> None: ...

    @abstractmethod
    def create(self, notification: Notification) -> Notification: ...
