"""SQL-backed database (docs/production-redesign/07, PG-2).

Implements the 12 repository interfaces with SQLAlchemy Core against the shared
schema. It is **engine-agnostic** — the production backend passes a Postgres engine;
tests pass an in-memory SQLite engine and run the *same* API test suite, which is the
parity guarantee (identical behaviour to `InMemoryDatabase`).

Semantics mirror `InMemoryDatabase` deliberately, including its quirks (e.g.
`documents.list_for_project` ignores `assignee_id`; `compare.get_or_create` matches on
project only): the goal is a drop-in swap, not a redesign. `create` and `update` are
both **upsert-by-PK**, matching the in-memory "set by key" behaviour.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, delete, func, insert, select, update

from ...models.domain import (
    User, Project, ProjectMember, AccessRequest, Version, Commit, AnalysisJob,
    Document, DocumentSection, DocumentAssignment, Function, CompareResult,
    DocumentDiff, Notification,
)
from ...repositories.interfaces import (
    IUserRepository, IProjectRepository, IProjectMemberRepository,
    IAccessRequestRepository, IVersionRepository, ICommitRepository,
    IAnalysisJobRepository, IDocumentRepository, IDocumentAssignmentRepository,
    IFunctionRepository, ICompareRepository, INotificationRepository,
)
from . import schema as s
from .mappers import to_row, from_row

UTC = timezone.utc


class _Base:
    def __init__(self, engine):
        self._engine = engine

    # --- small query helpers ------------------------------------------------
    def _all(self, stmt, cls) -> list:
        with self._engine.connect() as cx:
            return [from_row(cls, r) for r in cx.execute(stmt)]

    def _first(self, stmt, cls):
        with self._engine.connect() as cx:
            r = cx.execute(stmt).first()
            return from_row(cls, r) if r is not None else None

    def _put(self, table, pk: list[str], values: dict) -> None:
        """Upsert by primary key (matches in-memory 'store[key] = obj')."""
        with self._engine.begin() as cx:
            where = and_(*[table.c[k] == values[k] for k in pk])
            if cx.execute(update(table).where(where).values(**values)).rowcount == 0:
                cx.execute(insert(table).values(**values))

    def _exec(self, stmt) -> Any:
        with self._engine.begin() as cx:
            return cx.execute(stmt)


class _UserRepo(_Base, IUserRepository):
    def get_by_id(self, user_id):
        return self._first(select(s.users).where(s.users.c.id == user_id), User)

    def get_by_email(self, email):
        return self._first(select(s.users).where(s.users.c.email == email), User)

    def create(self, user):
        self._put(s.users, ["id"], to_row(user)); return user

    def update(self, user):
        self._put(s.users, ["id"], to_row(user)); return user

    def list_by_ids(self, ids):
        found = {u.id: u for u in self._all(select(s.users).where(s.users.c.id.in_(ids)), User)}
        return [found[i] for i in ids if i in found]        # preserve caller order

    def search(self, query, limit=10):
        q = (query or "").strip().lower()
        stmt = select(s.users)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(func.lower(s.users.c.name).like(like)
                              | func.lower(s.users.c.email).like(like))
        stmt = stmt.order_by(s.users.c.name).limit(limit)
        return self._all(stmt, User)


class _ProjectRepo(_Base, IProjectRepository):
    def list_for_user(self, user_id):
        m = s.project_members
        stmt = select(s.projects).where(s.projects.c.id.in_(
            select(m.c.project_id).where((m.c.user_id == user_id) & (m.c.status == "active"))))
        return self._all(stmt, Project)

    def get(self, project_id):
        return self._first(select(s.projects).where(s.projects.c.id == project_id), Project)

    def create(self, project):
        self._put(s.projects, ["id"], to_row(project)); return project

    def update(self, project):
        self._put(s.projects, ["id"], to_row(project)); return project

    def delete(self, project_id):
        self._exec(delete(s.projects).where(s.projects.c.id == project_id))

    def search(self, query):
        like = f"%{(query or '').lower()}%"
        stmt = select(s.projects).where(
            func.lower(s.projects.c.name).like(like)
            | func.lower(func.coalesce(s.projects.c.client, "")).like(like))
        return self._all(stmt, Project)


class _MemberRepo(_Base, IProjectMemberRepository):
    def list_members(self, project_id):
        m = s.project_members
        return self._all(select(m).where((m.c.project_id == project_id) & (m.c.status == "active")),
                         ProjectMember)

    def get_member(self, project_id, user_id):
        m = s.project_members
        return self._first(select(m).where((m.c.project_id == project_id) & (m.c.user_id == user_id)),
                           ProjectMember)

    def add_member(self, member):
        self._put(s.project_members, ["id"], to_row(member)); return member

    def update_member(self, member):
        self._put(s.project_members, ["id"], to_row(member)); return member

    def remove_member(self, project_id, user_id):
        m = s.project_members
        self._exec(delete(m).where((m.c.project_id == project_id) & (m.c.user_id == user_id)))

    def list_pending(self, project_id):
        m = s.project_members
        return self._all(select(m).where((m.c.project_id == project_id) & (m.c.status == "pending")),
                         ProjectMember)

    def cancel_invite(self, project_id, invite_id):
        self._exec(delete(s.project_members).where(s.project_members.c.id == invite_id))


class _AccessReqRepo(_Base, IAccessRequestRepository):
    def create(self, req):
        self._put(s.access_requests, ["id"], to_row(req)); return req

    def list_pending(self, project_id):
        a = s.access_requests
        return self._all(select(a).where((a.c.project_id == project_id) & (a.c.status == "pending")),
                         AccessRequest)

    def get(self, req_id):
        return self._first(select(s.access_requests).where(s.access_requests.c.id == req_id),
                           AccessRequest)

    def update(self, req):
        self._put(s.access_requests, ["id"], to_row(req)); return req


class _VersionRepo(_Base, IVersionRepository):
    def list_for_project(self, project_id):
        return self._all(select(s.versions).where(s.versions.c.project_id == project_id), Version)

    def get(self, version_id):
        return self._first(select(s.versions).where(s.versions.c.id == version_id), Version)

    def create(self, version):
        self._put(s.versions, ["id"], to_row(version)); return version

    def update(self, version):
        self._put(s.versions, ["id"], to_row(version)); return version

    def delete(self, version_id):
        self._exec(delete(s.versions).where(s.versions.c.id == version_id))

    def get_by_tag(self, project_id, tag):
        v = s.versions
        return self._first(select(v).where((v.c.project_id == project_id) & (v.c.version == tag)),
                           Version)


class _CommitRepo(_Base, ICommitRepository):
    def list_for_project(self, project_id, page=1, per_page=20):
        c = s.commits
        where = c.c.project_id == project_id
        with self._engine.connect() as cx:
            total = cx.execute(select(func.count()).select_from(c).where(where)).scalar_one()
            stmt = (select(c).where(where).order_by(c.c.committed_at.desc())
                    .limit(per_page).offset((page - 1) * per_page))
            items = [from_row(Commit, r) for r in cx.execute(stmt)]
        return items, total

    def get(self, project_id, sha):
        c = s.commits
        return self._first(select(c).where((c.c.project_id == project_id) & (c.c.sha == sha)), Commit)

    def upsert(self, commit):
        self._put(s.commits, ["project_id", "sha"], to_row(commit)); return commit


class _JobRepo(_Base, IAnalysisJobRepository):
    def create(self, job):
        self._put(s.analysis_jobs, ["id"], to_row(job)); return job

    def get(self, job_id):
        return self._first(select(s.analysis_jobs).where(s.analysis_jobs.c.id == job_id), AnalysisJob)

    def get_current(self, project_id):
        j = s.analysis_jobs
        stmt = (select(j).where((j.c.project_id == project_id) & (j.c.status != "cancelled"))
                .order_by(j.c.started_at.desc()).limit(1))
        return self._first(stmt, AnalysisJob)

    def update(self, job):
        self._put(s.analysis_jobs, ["id"], to_row(job)); return job


class _DocRepo(_Base, IDocumentRepository):
    def list_for_project(self, project_id, version_id=None, process=None, status=None,
                         assignee_id=None, query=None, page=1, per_page=20):
        d = s.documents
        conds = [d.c.project_id == project_id]
        if version_id:
            conds.append(d.c.version_id == version_id)
        if process:
            conds.append(d.c.process == process)
        if status:
            conds.append(d.c.status == status)
        if query:
            conds.append(func.lower(d.c.name).like(f"%{query.lower()}%"))
        # assignee_id is accepted but not filtered (parity with InMemoryDatabase).
        where = and_(*conds)
        with self._engine.connect() as cx:
            total = cx.execute(select(func.count()).select_from(d).where(where)).scalar_one()
            stmt = select(d).where(where).limit(per_page).offset((page - 1) * per_page)
            items = [from_row(Document, r) for r in cx.execute(stmt)]
        return items, total

    def get(self, document_id):
        return self._first(select(s.documents).where(s.documents.c.id == document_id), Document)

    def update(self, document):
        self._put(s.documents, ["id"], to_row(document)); return document

    def get_stats(self, project_id, version_id=None):
        d = s.documents
        conds = [d.c.project_id == project_id]
        if version_id:
            conds.append(d.c.version_id == version_id)
        stats = {"total": 0, "approved": 0, "in_review": 0, "never": 0, "unchanged": 0}
        with self._engine.connect() as cx:
            for statusval, n in cx.execute(
                    select(d.c.status, func.count()).where(and_(*conds)).group_by(d.c.status)):
                stats["total"] += n
                stats[statusval] = stats.get(statusval, 0) + n
        return stats

    def list_sections(self, document_id):
        sec = s.document_sections
        return self._all(select(sec).where(sec.c.document_id == document_id).order_by(sec.c.ord),
                         DocumentSection)

    def get_section(self, document_id, section_key):
        sec = s.document_sections
        return self._first(select(sec).where((sec.c.document_id == document_id)
                                             & (sec.c.section_key == section_key)), DocumentSection)

    def update_section(self, section):
        sec = s.document_sections
        row = to_row(section)
        with self._engine.begin() as cx:
            where = (sec.c.document_id == section.document_id) & (sec.c.section_key == section.section_key)
            if cx.execute(update(sec).where(where).values(**row)).rowcount == 0:
                cx.execute(insert(sec).values(**row))
        return section


class _AssignRepo(_Base, IDocumentAssignmentRepository):
    def list_for_document(self, document_id):
        a = s.document_assignments
        return self._all(select(a).where(a.c.document_id == document_id), DocumentAssignment)

    def assign(self, assignment):
        self._exec(insert(s.document_assignments).values(**to_row(assignment)))
        return assignment

    def remove(self, document_id, user_id):
        a = s.document_assignments
        self._exec(delete(a).where((a.c.document_id == document_id) & (a.c.user_id == user_id)))

    def batch_assign(self, assignments):
        for a in assignments:
            self.assign(a)


class _FunctionRepo(_Base, IFunctionRepository):
    def list_for_job(self, job_id):
        jf = s.job_functions
        return self._all(select(jf).where(jf.c.job_id == job_id), Function)

    def get(self, function_id):
        return self._first(select(s.job_functions).where(s.job_functions.c.id == function_id), Function)

    def update(self, function):
        # Update by id, leaving job_id (a storage key, not a domain field) untouched.
        row = to_row(function)
        self._exec(update(s.job_functions).where(s.job_functions.c.id == function.id).values(**row))
        return function

    def bulk_update_visibility(self, function_ids, is_visible):
        jf = s.job_functions
        self._exec(update(jf).where(jf.c.id.in_(function_ids)).values(is_visible=is_visible))

    def load_from_pipeline(self, pipeline_functions: dict) -> None:
        """Replace each job's functions (additive across jobs) — matches InMemoryDatabase."""
        jf = s.job_functions
        with self._engine.begin() as cx:
            for job_id, fns in pipeline_functions.items():
                cx.execute(delete(jf).where(jf.c.job_id == job_id))
                for f in fns:
                    cx.execute(insert(jf).values(job_id=job_id, **to_row(f)))


class _CompareRepo(_Base, ICompareRepository):
    def get_or_create(self, project_id, current_ref, baseline_ref):
        existing = self._first(
            select(s.compare_results).where(s.compare_results.c.project_id == project_id),
            CompareResult)
        if existing:
            return existing
        cr = CompareResult(str(uuid.uuid4()), project_id, current_ref, baseline_ref,
                           {"added": 0, "changed": 0, "removed": 0, "unchanged": 0})
        self._exec(insert(s.compare_results).values(**to_row(cr)))
        return cr

    def list_diffs(self, compare_id):
        dd = s.document_diffs
        return self._all(select(dd).where(dd.c.compare_result_id == compare_id), DocumentDiff)

    def get_document_diff(self, compare_id, document_id):
        dd = s.document_diffs
        return self._first(select(dd).where((dd.c.compare_result_id == compare_id)
                                            & (dd.c.document_id == document_id)), DocumentDiff)


class _NotifRepo(_Base, INotificationRepository):
    def list_unread(self, user_id):
        n = s.notifications
        return self._all(select(n).where((n.c.user_id == user_id) & (n.c.read_at.is_(None))),
                         Notification)

    def mark_read(self, notification_id):
        n = s.notifications
        res = self._exec(update(n).where(n.c.id == notification_id).values(read_at=datetime.now(UTC)))
        if res.rowcount == 0:
            raise KeyError(notification_id)
        return self._first(select(n).where(n.c.id == notification_id), Notification)

    def mark_all_read(self, user_id):
        n = s.notifications
        self._exec(update(n).where((n.c.user_id == user_id) & (n.c.read_at.is_(None)))
                   .values(read_at=datetime.now(UTC)))

    def create(self, notification):
        self._exec(insert(s.notifications).values(**to_row(notification)))
        return notification


class SqlDatabase:
    """Drop-in replacement for InMemoryDatabase over any SQLAlchemy engine.

    `engine=None` uses the process Postgres engine (production); tests pass a SQLite
    engine. `create_schema=True` builds the tables (SQLite tests); production applies
    Alembic migrations instead.
    """

    def __init__(self, engine=None, *, create_schema: bool = False):
        if engine is None:
            from core.db import get_engine
            engine = get_engine()
        self._engine = engine
        if create_schema:
            s.metadata.create_all(engine)
        self.users = _UserRepo(engine)
        self.projects = _ProjectRepo(engine)
        self.members = _MemberRepo(engine)
        self.access_reqs = _AccessReqRepo(engine)
        self.versions = _VersionRepo(engine)
        self.commits = _CommitRepo(engine)
        self.jobs = _JobRepo(engine)
        self.documents = _DocRepo(engine)
        self.assignments = _AssignRepo(engine)
        self.functions = _FunctionRepo(engine)
        self.compare = _CompareRepo(engine)
        self.notifications = _NotifRepo(engine)

    def seed(self) -> "SqlDatabase":
        """Load the same seed data InMemoryDatabase ships with (parity tests / demos)."""
        from ..in_memory import (
            _seed_users, _seed_projects, _seed_members, _seed_versions, _seed_commits,
            _seed_jobs, _seed_documents, _seed_sections, _seed_assignments,
            _seed_functions, _seed_notifications, _seed_compare,
        )
        for u in _seed_users().values():
            self.users.create(u)
        for p in _seed_projects().values():
            self.projects.create(p)
        for m in _seed_members().values():
            self.members.add_member(m)
        for v in _seed_versions().values():
            self.versions.create(v)
        for c in _seed_commits().values():
            self.commits.upsert(c)
        for j in _seed_jobs().values():
            self.jobs.create(j)
        for d in _seed_documents().values():
            self.documents.update(d)
        for secs in _seed_sections().values():
            for sec in secs:
                self.documents.update_section(sec)
        for asgs in _seed_assignments().values():
            for a in asgs:
                self.assignments.assign(a)
        self.functions.load_from_pipeline(_seed_functions())
        for ns in _seed_notifications().values():
            for note in ns:
                self.notifications.create(note)
        results, diffs = _seed_compare()
        with self._engine.begin() as cx:
            for cr in results.values():
                cx.execute(insert(s.compare_results).values(**to_row(cr)))
            for dlist in diffs.values():
                for d in dlist:
                    cx.execute(insert(s.document_diffs).values(**to_row(d)))
        return self
