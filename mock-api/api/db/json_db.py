"""
JSON-file database adapter.

Treats the ``model/`` directory (created by the document-generation pipeline)
as a persistent key-value store.  Every aggregate (users, projects, …) is
stored in its own JSON file under ``api/db/data/`` **except** for the
pipeline artefacts (functions, analysis jobs, documents) which are read
directly from the ``model/`` output files produced by Phases 1-4.

Layout
------
api/db/data/            ← read/write store managed by this adapter
  users.json
  projects.json
  members.json
  access_requests.json
  versions.json
  commits.json
  jobs.json
  documents.json
  sections.json
  assignments.json
  functions.json
  notifications.json
  compare_results.json
  compare_diffs.json

model/                  ← pipeline output (read-only from the API's perspective)
  functions.json        ← loaded at start; overwrites functions store
  metadata.json         ← used to seed project name / layer info

Swapping from InMemoryDatabase to JsonDatabase
----------------------------------------------
Change **one line** in ``api/db/session.py``::

    from .json_db import JsonDatabase
    _db = JsonDatabase()          # path defaults to project root

All routes and services continue to work unchanged — they only see the
repository interfaces defined in ``api/repositories/interfaces.py``.

Write-through
-------------
Every mutating operation (create / update / delete) serialises the full
in-memory collection back to the corresponding JSON file immediately.
There is no deferred flushing, so the on-disk state is always consistent
with the in-memory state after each call returns.

Initialisation
--------------
1. If ``api/db/data/`` files exist they are loaded as-is (persistent mode).
2. If they are absent the adapter seeds itself from the same dummy data used
   by ``InMemoryDatabase`` and writes the files to disk so subsequent
   restarts are persistent.
3. If ``model/functions.json`` exists the seeded/loaded functions store is
   **replaced** with the pipeline output so the API always reflects the
   latest analysis run.
"""

from __future__ import annotations

import copy
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..models.domain import (
    User, Project, ProjectMember, Version, Commit, AnalysisJob,
    AnalysisPhase, Document, DocumentSection, DocumentAssignment,
    Function, CompareResult, DocumentDiff, Notification, AccessRequest,
)
from ..repositories.interfaces import (
    IUserRepository, IProjectRepository, IProjectMemberRepository,
    IAccessRequestRepository, IVersionRepository, ICommitRepository,
    IAnalysisJobRepository, IDocumentRepository,
    IDocumentAssignmentRepository, IFunctionRepository,
    ICompareRepository, INotificationRepository,
)

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _find_root() -> Path:
    """Walk up from this file to find the project root (contains run.py)."""
    here = Path(__file__).resolve().parent
    for candidate in [here, here.parent, here.parent.parent, here.parent.parent.parent]:
        if (candidate / "run.py").exists():
            return candidate
    return here.parent.parent.parent   # fallback


def _data_dir(root: Path) -> Path:
    d = root / "api" / "db" / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _model_dir(root: Path) -> Path:
    return root / "model"


# ---------------------------------------------------------------------------
# JSON serialisation helpers
# ---------------------------------------------------------------------------
# datetime / date objects are not JSON-serialisable by default.

_DT_FMT = "%Y-%m-%dT%H:%M:%S%z"
_DATE_FMT = "%Y-%m-%d"


def _default(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.strftime(_DT_FMT)
    from datetime import date as _date
    if isinstance(obj, _date):
        return obj.strftime(_DATE_FMT)
    raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")


def _parse_dt(s) -> Optional[datetime]:
    if s is None:
        return None
    if isinstance(s, datetime):
        return s
    try:
        return datetime.strptime(s, _DT_FMT)
    except ValueError:
        # Try without tz
        return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=UTC)


def _parse_date(s):
    from datetime import date as _date
    if s is None:
        return None
    if isinstance(s, _date):
        return s
    return _date.fromisoformat(s)


# ---------------------------------------------------------------------------
# Generic read / write for a single collection file
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    """Load JSON from path, return empty dict on missing/corrupt file."""
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_json(path: Path, data: Any) -> None:
    """Atomically write data to path as JSON."""
    tmp = path.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=_default)
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Domain object <-> dict conversions
# ---------------------------------------------------------------------------

def _user_to_dict(u: User) -> dict:
    return {
        "id": u.id, "email": u.email, "name": u.name,
        "initials": u.initials, "avatar_url": u.avatar_url,
        "hashed_password": u.hashed_password,
        "created_at": u.created_at,
    }


def _user_from_dict(d: dict) -> User:
    return User(
        id=d["id"], email=d["email"], name=d["name"],
        initials=d["initials"], avatar_url=d.get("avatar_url"),
        hashed_password=d["hashed_password"],
        created_at=_parse_dt(d["created_at"]),
    )


def _project_to_dict(p: Project) -> dict:
    return {
        "id": p.id, "org_id": p.org_id, "name": p.name,
        "client": p.client, "compliance_standard": p.compliance_standard,
        "repo_url": p.repo_url, "repo_provider": p.repo_provider,
        "default_branch": p.default_branch, "build_config": p.build_config,
        "architecture_layers": p.architecture_layers, "status": p.status,
        "created_by": p.created_by, "created_at": p.created_at,
        "updated_at": p.updated_at,
    }


def _project_from_dict(d: dict) -> Project:
    return Project(
        id=d["id"], org_id=d["org_id"], name=d["name"],
        client=d["client"], compliance_standard=d["compliance_standard"],
        repo_url=d["repo_url"], repo_provider=d["repo_provider"],
        default_branch=d["default_branch"], build_config=d.get("build_config", {}),
        architecture_layers=d.get("architecture_layers", []),
        status=d["status"], created_by=d["created_by"],
        created_at=_parse_dt(d["created_at"]),
        updated_at=_parse_dt(d["updated_at"]),
    )


def _member_to_dict(m: ProjectMember) -> dict:
    return {
        "id": m.id, "project_id": m.project_id, "user_id": m.user_id,
        "role": m.role, "status": m.status, "invited_by": m.invited_by,
        "invited_at": m.invited_at, "joined_at": m.joined_at,
    }


def _member_from_dict(d: dict) -> ProjectMember:
    return ProjectMember(
        id=d["id"], project_id=d["project_id"], user_id=d["user_id"],
        role=d["role"], status=d["status"], invited_by=d["invited_by"],
        invited_at=_parse_dt(d["invited_at"]),
        joined_at=_parse_dt(d.get("joined_at")),
    )


def _access_req_to_dict(r: AccessRequest) -> dict:
    return {
        "id": r.id, "project_id": r.project_id, "user_id": r.user_id,
        "requested_at": r.requested_at, "status": r.status,
        "resolved_by": r.resolved_by, "resolved_at": r.resolved_at,
    }


def _access_req_from_dict(d: dict) -> AccessRequest:
    return AccessRequest(
        id=d["id"], project_id=d["project_id"], user_id=d["user_id"],
        requested_at=_parse_dt(d["requested_at"]), status=d["status"],
        resolved_by=d.get("resolved_by"), resolved_at=_parse_dt(d.get("resolved_at")),
    )


def _version_to_dict(v: Version) -> dict:
    return {
        "id": v.id, "project_id": v.project_id, "tag": v.tag,
        "commit_sha": v.commit_sha, "branch": v.branch,
        "description": v.description, "status": v.status,
        "docs_count": v.docs_count, "created_by": v.created_by,
        "created_at": v.created_at,
    }


def _version_from_dict(d: dict) -> Version:
    return Version(
        id=d["id"], project_id=d["project_id"], tag=d["tag"],
        commit_sha=d["commit_sha"], branch=d["branch"],
        description=d["description"], status=d["status"],
        docs_count=d["docs_count"], created_by=d["created_by"],
        created_at=_parse_dt(d["created_at"]),
    )


def _commit_to_dict(c: Commit) -> dict:
    return {
        "sha": c.sha, "project_id": c.project_id, "branch": c.branch,
        "message": c.message, "author_name": c.author_name,
        "author_email": c.author_email, "committed_at": c.committed_at,
        "has_version": c.has_version, "version_id": c.version_id,
        "doc_status": c.doc_status,
    }


def _commit_from_dict(d: dict) -> Commit:
    return Commit(
        sha=d["sha"], project_id=d["project_id"], branch=d["branch"],
        message=d["message"], author_name=d["author_name"],
        author_email=d["author_email"],
        committed_at=_parse_dt(d["committed_at"]),
        has_version=d["has_version"], version_id=d.get("version_id"),
        doc_status=d["doc_status"],
    )


def _phase_to_dict(p: AnalysisPhase) -> dict:
    return {
        "number": p.number, "name": p.name,
        "status": p.status, "duration_seconds": p.duration_seconds,
    }


def _phase_from_dict(d: dict) -> AnalysisPhase:
    return AnalysisPhase(
        number=d["number"], name=d["name"],
        status=d["status"], duration_seconds=d.get("duration_seconds"),
    )


def _job_to_dict(j: AnalysisJob) -> dict:
    return {
        "id": j.id, "project_id": j.project_id, "commit_sha": j.commit_sha,
        "version_id": j.version_id,
        "reference_version_id": j.reference_version_id,
        "status": j.status,
        "pause_after_phase1": j.pause_after_phase1,
        "layer_filter": j.layer_filter,
        "phase": j.phase, "phase_pct": j.phase_pct,
        "current_activity": j.current_activity,
        "activity_detail": j.activity_detail,
        "elapsed_seconds": j.elapsed_seconds,
        "eta_seconds": j.eta_seconds,
        "phases": [_phase_to_dict(p) for p in j.phases],
        "started_at": j.started_at, "completed_at": j.completed_at,
        "error_message": j.error_message, "branch": j.branch,
        "version_tag": j.version_tag,
    }


def _job_from_dict(d: dict) -> AnalysisJob:
    return AnalysisJob(
        id=d["id"], project_id=d["project_id"], commit_sha=d["commit_sha"],
        version_id=d.get("version_id"),
        reference_version_id=d.get("reference_version_id"),
        status=d["status"],
        pause_after_phase1=d.get("pause_after_phase1", False),
        layer_filter=d.get("layer_filter"),
        phase=d["phase"], phase_pct=d["phase_pct"],
        current_activity=d["current_activity"],
        activity_detail=d.get("activity_detail", ""),
        elapsed_seconds=d["elapsed_seconds"],
        eta_seconds=d.get("eta_seconds"),
        phases=[_phase_from_dict(p) for p in d.get("phases", [])],
        started_at=_parse_dt(d["started_at"]),
        completed_at=_parse_dt(d.get("completed_at")),
        error_message=d.get("error_message"),
        branch=d.get("branch", "main"),
        version_tag=d.get("version_tag"),
    )


def _doc_to_dict(doc: Document) -> dict:
    return {
        "id": doc.id, "project_id": doc.project_id,
        "version_id": doc.version_id, "process": doc.process,
        "name": doc.name, "subtitle": doc.subtitle,
        "layer": doc.layer, "group": doc.group, "status": doc.status,
        "due_date": doc.due_date, "created_at": doc.created_at,
        "updated_at": doc.updated_at,
    }


def _doc_from_dict(d: dict) -> Document:
    return Document(
        id=d["id"], project_id=d["project_id"], version_id=d["version_id"],
        process=d["process"], name=d["name"], subtitle=d["subtitle"],
        layer=d["layer"], group=d["group"], status=d["status"],
        due_date=_parse_date(d.get("due_date")),
        created_at=_parse_dt(d["created_at"]),
        updated_at=_parse_dt(d["updated_at"]),
    )


def _section_to_dict(s: DocumentSection) -> dict:
    return {
        "id": s.id, "document_id": s.document_id,
        "section_key": s.section_key, "title": s.title,
        "order": s.order, "content": s.content,
        "review_state": s.review_state,
        "reviewed_by": s.reviewed_by, "reviewed_at": s.reviewed_at,
    }


def _section_from_dict(d: dict) -> DocumentSection:
    return DocumentSection(
        id=d["id"], document_id=d["document_id"],
        section_key=d["section_key"], title=d["title"],
        order=d["order"], content=d["content"],
        review_state=d.get("review_state"),
        reviewed_by=d.get("reviewed_by"),
        reviewed_at=_parse_dt(d.get("reviewed_at")),
    )


def _assignment_to_dict(a: DocumentAssignment) -> dict:
    return {
        "id": a.id, "document_id": a.document_id,
        "user_id": a.user_id, "assigned_by": a.assigned_by,
        "assigned_at": a.assigned_at,
    }


def _assignment_from_dict(d: dict) -> DocumentAssignment:
    return DocumentAssignment(
        id=d["id"], document_id=d["document_id"],
        user_id=d["user_id"], assigned_by=d["assigned_by"],
        assigned_at=_parse_dt(d["assigned_at"]),
    )


def _function_to_dict(f: Function) -> dict:
    return {
        "id": f.id, "project_id": f.project_id, "version_id": f.version_id,
        "name": f.name, "file_path": f.file_path,
        "layer": f.layer, "group": f.group,
        "is_visible": f.is_visible, "is_new": f.is_new,
        "description": f.description,
    }


def _function_from_dict(d: dict) -> Function:
    return Function(
        id=d["id"], project_id=d["project_id"], version_id=d.get("version_id", ""),
        name=d["name"], file_path=d.get("file_path", ""),
        layer=d.get("layer", ""), group=d.get("group", ""),
        is_visible=d.get("is_visible", True),
        is_new=d.get("is_new", False),
        description=d.get("description", ""),
    )


def _notif_to_dict(n: Notification) -> dict:
    return {
        "id": n.id, "user_id": n.user_id, "project_id": n.project_id,
        "type": n.type, "message": n.message,
        "read_at": n.read_at, "created_at": n.created_at,
    }


def _notif_from_dict(d: dict) -> Notification:
    return Notification(
        id=d["id"], user_id=d["user_id"], project_id=d["project_id"],
        type=d["type"], message=d["message"],
        read_at=_parse_dt(d.get("read_at")),
        created_at=_parse_dt(d["created_at"]),
    )


def _compare_result_to_dict(cr: CompareResult) -> dict:
    return {
        "id": cr.id, "project_id": cr.project_id,
        "current_version_id": cr.current_version_id,
        "baseline_version_id": cr.baseline_version_id,
        "diff_summary": cr.diff_summary,
    }


def _compare_result_from_dict(d: dict) -> CompareResult:
    return CompareResult(
        id=d["id"], project_id=d["project_id"],
        current_version_id=d["current_version_id"],
        baseline_version_id=d["baseline_version_id"],
        diff_summary=d.get("diff_summary", {}),
    )


def _diff_to_dict(diff: DocumentDiff) -> dict:
    return {
        "id": diff.id, "compare_result_id": diff.compare_result_id,
        "document_id": diff.document_id, "diff_type": diff.diff_type,
        "sections_changed": diff.sections_changed,
    }


def _diff_from_dict(d: dict) -> DocumentDiff:
    return DocumentDiff(
        id=d["id"], compare_result_id=d["compare_result_id"],
        document_id=d["document_id"], diff_type=d["diff_type"],
        sections_changed=d.get("sections_changed", []),
    )


# ---------------------------------------------------------------------------
# Functions loaded from model/functions.json (pipeline output)
# ---------------------------------------------------------------------------

def _load_pipeline_functions(
    model_dir: Path,
    project_id: str = "p1",
    version_id: str = "ver3",
    job_id: str = "job1",
) -> Optional[dict[str, list[Function]]]:
    """
    Load functions from model/functions.json (Phase 1/2 pipeline output).

    The pipeline stores functions as a flat dict keyed by qualified function
    name.  We project each entry into the Function domain model.

    Returns None if the file doesn't exist (pipeline hasn't run yet).
    """
    path = model_dir / "functions.json"
    if not path.exists():
        return None

    try:
        with path.open(encoding="utf-8") as f:
            raw: dict = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

    # Try to infer project/version from metadata.json
    meta_path = model_dir / "metadata.json"
    if meta_path.exists():
        try:
            with meta_path.open(encoding="utf-8") as f:
                meta = json.load(f)
            project_id = meta.get("projectName", project_id)
        except Exception:
            pass

    functions: list[Function] = []
    for fn_key, fn_data in raw.items():
        if not isinstance(fn_data, dict):
            continue
        fn_name = fn_data.get("name") or fn_key.split("::")[-1]
        file_path = fn_data.get("file", fn_data.get("filePath", ""))
        layer = fn_data.get("layer", fn_data.get("layerName", ""))
        group = fn_data.get("componentName", fn_data.get("group", ""))
        description = fn_data.get("description", "")
        is_visible = fn_data.get("isVisible", fn_data.get("is_visible", True))
        fn_id = fn_data.get("id", str(uuid.uuid4()))

        functions.append(Function(
            id=fn_id,
            project_id=project_id,
            version_id=version_id,
            name=fn_name,
            file_path=file_path,
            layer=layer,
            group=group,
            is_visible=bool(is_visible),
            is_new=False,
            description=description,
        ))

    return {job_id: functions}


# ---------------------------------------------------------------------------
# Default seed data (mirrors InMemoryDatabase seed data)
# Used only when data/ files do not already exist.
# ---------------------------------------------------------------------------

def _default_seed() -> dict[str, Any]:
    """Return the same seed data as InMemoryDatabase, serialised to plain dicts."""
    # We import the in-memory seed functions to avoid duplicating them.
    from .in_memory import (
        _seed_users, _seed_projects, _seed_members, _seed_versions,
        _seed_commits, _seed_jobs, _seed_documents, _seed_sections,
        _seed_assignments, _seed_functions, _seed_notifications, _seed_compare,
    )
    cmp_results, cmp_diffs = _seed_compare()
    sections_raw = _seed_sections()
    assign_raw = _seed_assignments()
    fn_raw = _seed_functions()
    notif_raw = _seed_notifications()

    return {
        "users":    {k: _user_to_dict(v) for k, v in _seed_users().items()},
        "projects": {k: _project_to_dict(v) for k, v in _seed_projects().items()},
        "members":  {k: _member_to_dict(v) for k, v in _seed_members().items()},
        "access_requests": {},
        "versions": {k: _version_to_dict(v) for k, v in _seed_versions().items()},
        "commits":  {k: _commit_to_dict(v) for k, v in _seed_commits().items()},
        "jobs":     {k: _job_to_dict(v) for k, v in _seed_jobs().items()},
        "documents": {k: _doc_to_dict(v) for k, v in _seed_documents().items()},
        "sections": {
            doc_id: [_section_to_dict(s) for s in secs]
            for doc_id, secs in sections_raw.items()
        },
        "assignments": {
            doc_id: [_assignment_to_dict(a) for a in assigns]
            for doc_id, assigns in assign_raw.items()
        },
        "functions": {
            job_id: [_function_to_dict(f) for f in fns]
            for job_id, fns in fn_raw.items()
        },
        "notifications": {
            uid: [_notif_to_dict(n) for n in ns]
            for uid, ns in notif_raw.items()
        },
        "compare_results": {k: _compare_result_to_dict(v) for k, v in cmp_results.items()},
        "compare_diffs": {
            cid: [_diff_to_dict(d) for d in diffs]
            for cid, diffs in cmp_diffs.items()
        },
    }


# ---------------------------------------------------------------------------
# Concrete JSON-backed repository implementations
# ---------------------------------------------------------------------------

class _JsonUserRepo(IUserRepository):
    def __init__(self, store: dict[str, dict], path: Path):
        self._store = store   # id -> raw dict
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def _obj(self, d: dict) -> User:
        return _user_from_dict(d)

    def get_by_id(self, user_id):
        d = self._store.get(user_id)
        return copy.deepcopy(self._obj(d)) if d else None

    def get_by_email(self, email):
        for d in self._store.values():
            if d["email"] == email:
                return copy.deepcopy(self._obj(d))
        return None

    def create(self, user: User) -> User:
        self._store[user.id] = _user_to_dict(user)
        self._save()
        return copy.deepcopy(user)

    def update(self, user: User) -> User:
        self._store[user.id] = _user_to_dict(user)
        self._save()
        return copy.deepcopy(user)

    def list_by_ids(self, ids):
        return [copy.deepcopy(self._obj(self._store[i])) for i in ids if i in self._store]

    def search(self, query, limit=10):
        q = (query or "").strip().lower()
        matches = [
            self._obj(d) for d in self._store.values()
            if not q or q in d["name"].lower() or q in d["email"].lower()
        ]
        matches.sort(key=lambda u: u.name.lower())
        return [copy.deepcopy(u) for u in matches[:limit]]


class _JsonProjectRepo(IProjectRepository):
    def __init__(self, store: dict[str, dict], members_store: dict[str, dict], path: Path):
        self._store = store
        self._members = members_store
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def list_for_user(self, user_id):
        project_ids = {
            d["project_id"] for d in self._members.values()
            if d["user_id"] == user_id and d["status"] == "active"
        }
        return [copy.deepcopy(_project_from_dict(d)) for d in self._store.values() if d["id"] in project_ids]

    def get(self, project_id):
        d = self._store.get(project_id)
        return copy.deepcopy(_project_from_dict(d)) if d else None

    def create(self, project: Project) -> Project:
        self._store[project.id] = _project_to_dict(project)
        self._save()
        return copy.deepcopy(project)

    def update(self, project: Project) -> Project:
        self._store[project.id] = _project_to_dict(project)
        self._save()
        return copy.deepcopy(project)

    def delete(self, project_id):
        self._store.pop(project_id, None)
        self._save()

    def search(self, query):
        q = query.lower()
        return [
            copy.deepcopy(_project_from_dict(d)) for d in self._store.values()
            if q in d["name"].lower() or q in d.get("client", "").lower()
        ]


class _JsonMemberRepo(IProjectMemberRepository):
    def __init__(self, store: dict[str, dict], path: Path):
        self._store = store
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def _project_members(self, project_id):
        return [d for d in self._store.values() if d["project_id"] == project_id]

    def list_members(self, project_id):
        return [copy.deepcopy(_member_from_dict(d)) for d in self._project_members(project_id) if d["status"] == "active"]

    def get_member(self, project_id, user_id):
        for d in self._project_members(project_id):
            if d["user_id"] == user_id:
                return copy.deepcopy(_member_from_dict(d))
        return None

    def add_member(self, member: ProjectMember) -> ProjectMember:
        self._store[member.id] = _member_to_dict(member)
        self._save()
        return copy.deepcopy(member)

    def update_member(self, member: ProjectMember) -> ProjectMember:
        self._store[member.id] = _member_to_dict(member)
        self._save()
        return copy.deepcopy(member)

    def remove_member(self, project_id, user_id):
        to_del = [k for k, d in self._store.items()
                  if d["project_id"] == project_id and d["user_id"] == user_id]
        for k in to_del:
            del self._store[k]
        self._save()

    def list_pending(self, project_id):
        return [copy.deepcopy(_member_from_dict(d)) for d in self._project_members(project_id) if d["status"] == "pending"]

    def cancel_invite(self, project_id, invite_id):
        self._store.pop(invite_id, None)
        self._save()


class _JsonAccessReqRepo(IAccessRequestRepository):
    def __init__(self, store: dict[str, dict], path: Path):
        self._store = store
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def create(self, req: AccessRequest) -> AccessRequest:
        self._store[req.id] = _access_req_to_dict(req)
        self._save()
        return copy.deepcopy(req)

    def list_pending(self, project_id):
        return [
            copy.deepcopy(_access_req_from_dict(d)) for d in self._store.values()
            if d["project_id"] == project_id and d["status"] == "pending"
        ]

    def get(self, req_id):
        d = self._store.get(req_id)
        return copy.deepcopy(_access_req_from_dict(d)) if d else None

    def update(self, req: AccessRequest) -> AccessRequest:
        self._store[req.id] = _access_req_to_dict(req)
        self._save()
        return copy.deepcopy(req)


class _JsonVersionRepo(IVersionRepository):
    def __init__(self, store: dict[str, dict], path: Path):
        self._store = store
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def list_for_project(self, project_id):
        return [copy.deepcopy(_version_from_dict(d)) for d in self._store.values() if d["project_id"] == project_id]

    def get(self, version_id):
        d = self._store.get(version_id)
        return copy.deepcopy(_version_from_dict(d)) if d else None

    def create(self, version: Version) -> Version:
        self._store[version.id] = _version_to_dict(version)
        self._save()
        return copy.deepcopy(version)

    def update(self, version: Version) -> Version:
        self._store[version.id] = _version_to_dict(version)
        self._save()
        return copy.deepcopy(version)

    def delete(self, version_id):
        self._store.pop(version_id, None)
        self._save()

    def get_by_tag(self, project_id, tag):
        for d in self._store.values():
            if d["project_id"] == project_id and d["tag"] == tag:
                return copy.deepcopy(_version_from_dict(d))
        return None


class _JsonCommitRepo(ICommitRepository):
    def __init__(self, store: dict[str, dict], path: Path):
        self._store = store
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def list_for_project(self, project_id, page=1, per_page=20):
        items = [_commit_from_dict(d) for d in self._store.values() if d["project_id"] == project_id]
        items.sort(key=lambda c: c.committed_at, reverse=True)
        total = len(items)
        start = (page - 1) * per_page
        return [copy.deepcopy(c) for c in items[start:start + per_page]], total

    def get(self, project_id, sha):
        d = self._store.get(f"{project_id}:{sha}")
        return copy.deepcopy(_commit_from_dict(d)) if d else None

    def upsert(self, commit: Commit) -> Commit:
        self._store[f"{commit.project_id}:{commit.sha}"] = _commit_to_dict(commit)
        self._save()
        return copy.deepcopy(commit)


class _JsonJobRepo(IAnalysisJobRepository):
    def __init__(self, store: dict[str, dict], path: Path):
        self._store = store
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def create(self, job: AnalysisJob) -> AnalysisJob:
        self._store[job.id] = _job_to_dict(job)
        self._save()
        return copy.deepcopy(job)

    def get(self, job_id):
        d = self._store.get(job_id)
        return copy.deepcopy(_job_from_dict(d)) if d else None

    def get_current(self, project_id):
        candidates = [
            _job_from_dict(d) for d in self._store.values()
            if d["project_id"] == project_id and d["status"] != "cancelled"
        ]
        if not candidates:
            return None
        return copy.deepcopy(max(candidates, key=lambda j: j.started_at))

    def update(self, job: AnalysisJob) -> AnalysisJob:
        self._store[job.id] = _job_to_dict(job)
        self._save()
        return copy.deepcopy(job)


class _JsonDocRepo(IDocumentRepository):
    def __init__(self, store: dict[str, dict], sections: dict[str, list[dict]], doc_path: Path, sec_path: Path):
        self._store = store
        self._sections = sections
        self._doc_path = doc_path
        self._sec_path = sec_path

    def _save(self):
        _save_json(self._doc_path, self._store)
        _save_json(self._sec_path, self._sections)

    def list_for_project(self, project_id, version_id=None, process=None,
                         status=None, assignee_id=None, query=None, page=1, per_page=20):
        items = [d for d in self._store.values() if d["project_id"] == project_id]
        if version_id:
            items = [d for d in items if d["version_id"] == version_id]
        if process:
            items = [d for d in items if d["process"] == process]
        if status:
            items = [d for d in items if d["status"] == status]
        if query:
            q = query.lower()
            items = [d for d in items if q in d["name"].lower()]
        total = len(items)
        start = (page - 1) * per_page
        return [copy.deepcopy(_doc_from_dict(d)) for d in items[start:start + per_page]], total

    def get(self, document_id):
        d = self._store.get(document_id)
        return copy.deepcopy(_doc_from_dict(d)) if d else None

    def update(self, document: Document) -> Document:
        self._store[document.id] = _doc_to_dict(document)
        self._save()
        return copy.deepcopy(document)

    def get_stats(self, project_id, version_id=None):
        items = [d for d in self._store.values() if d["project_id"] == project_id]
        if version_id:
            items = [d for d in items if d["version_id"] == version_id]
        stats: dict[str, int] = {"total": 0, "approved": 0, "in_review": 0, "never": 0, "unchanged": 0}
        for d in items:
            stats["total"] += 1
            stats[d["status"]] = stats.get(d["status"], 0) + 1
        return stats

    def list_sections(self, document_id):
        secs = [_section_from_dict(d) for d in self._sections.get(document_id, [])]
        return [copy.deepcopy(s) for s in sorted(secs, key=lambda s: s.order)]

    def get_section(self, document_id, section_key):
        for d in self._sections.get(document_id, []):
            if d["section_key"] == section_key:
                return copy.deepcopy(_section_from_dict(d))
        return None

    def update_section(self, section: DocumentSection) -> DocumentSection:
        secs = self._sections.setdefault(section.document_id, [])
        for i, d in enumerate(secs):
            if d["section_key"] == section.section_key:
                secs[i] = _section_to_dict(section)
                self._save()
                return copy.deepcopy(section)
        secs.append(_section_to_dict(section))
        self._save()
        return copy.deepcopy(section)


class _JsonAssignRepo(IDocumentAssignmentRepository):
    def __init__(self, store: dict[str, list[dict]], path: Path):
        self._store = store   # doc_id -> [dict]
        self._path = path

    def _save(self):
        _save_json(self._path, self._store)

    def list_for_document(self, document_id):
        return [copy.deepcopy(_assignment_from_dict(d)) for d in self._store.get(document_id, [])]

    def assign(self, assignment: DocumentAssignment) -> DocumentAssignment:
        lst = self._store.setdefault(assignment.document_id, [])
        lst.append(_assignment_to_dict(assignment))
        self._save()
        return copy.deepcopy(assignment)

    def remove(self, document_id, user_id):
        self._store[document_id] = [
            d for d in self._store.get(document_id, []) if d["user_id"] != user_id
        ]
        self._save()

    def batch_assign(self, assignments):
        for a in assignments:
            self.assign(a)


class _JsonFunctionRepo(IFunctionRepository):
    def __init__(self, store: dict[str, list[dict]], path: Path):
        self._store = store     # job_id -> [dict]
        self._path = path
        self._by_id: dict[str, dict] = {
            d["id"]: d for fns in store.values() for d in fns
        }

    def _save(self):
        _save_json(self._path, self._store)

    def list_for_job(self, job_id):
        return [copy.deepcopy(_function_from_dict(d)) for d in self._store.get(job_id, [])]

    def get(self, function_id):
        d = self._by_id.get(function_id)
        return copy.deepcopy(_function_from_dict(d)) if d else None

    def update(self, function: Function) -> Function:
        fd = _function_to_dict(function)
        self._by_id[function.id] = fd
        for job_id, fns in self._store.items():
            for i, d in enumerate(fns):
                if d["id"] == function.id:
                    fns[i] = fd
        self._save()
        return copy.deepcopy(function)

    def bulk_update_visibility(self, function_ids, is_visible):
        for fid in function_ids:
            d = self._by_id.get(fid)
            if d:
                d["is_visible"] = is_visible
                for fns in self._store.values():
                    for fd in fns:
                        if fd["id"] == fid:
                            fd["is_visible"] = is_visible
        self._save()

    def load_from_pipeline(self, pipeline_functions: dict[str, list[Function]]) -> None:
        """
        Replace the current functions store with data read from model/functions.json.
        Called during initialisation when the pipeline output is available.
        """
        self._store = {
            job_id: [_function_to_dict(f) for f in fns]
            for job_id, fns in pipeline_functions.items()
        }
        self._by_id = {
            d["id"]: d for fns in self._store.values() for d in fns
        }
        self._save()


class _JsonCompareRepo(ICompareRepository):
    def __init__(self, results: dict[str, dict], diffs: dict[str, list[dict]],
                 res_path: Path, diff_path: Path):
        self._results = results
        self._diffs = diffs
        self._res_path = res_path
        self._diff_path = diff_path

    def _save(self):
        _save_json(self._res_path, self._results)
        _save_json(self._diff_path, self._diffs)

    def get_or_create(self, project_id, current_ref, baseline_ref):
        for d in self._results.values():
            if d["project_id"] == project_id:
                return copy.deepcopy(_compare_result_from_dict(d))
        cr = CompareResult(
            str(uuid.uuid4()), project_id, current_ref, baseline_ref,
            {"added": 0, "changed": 0, "removed": 0, "unchanged": 0},
        )
        self._results[cr.id] = _compare_result_to_dict(cr)
        self._save()
        return copy.deepcopy(cr)

    def list_diffs(self, compare_id):
        return [copy.deepcopy(_diff_from_dict(d)) for d in self._diffs.get(compare_id, [])]

    def get_document_diff(self, compare_id, document_id):
        for d in self._diffs.get(compare_id, []):
            if d["document_id"] == document_id:
                return copy.deepcopy(_diff_from_dict(d))
        return None


class _JsonNotifRepo(INotificationRepository):
    def __init__(self, store: dict[str, list[dict]], path: Path):
        self._store = store   # user_id -> [dict]
        self._path = path
        self._by_id: dict[str, dict] = {
            d["id"]: d for ns in store.values() for d in ns
        }

    def _save(self):
        _save_json(self._path, self._store)

    def list_unread(self, user_id):
        return [
            copy.deepcopy(_notif_from_dict(d))
            for d in self._store.get(user_id, [])
            if d.get("read_at") is None
        ]

    def mark_read(self, notification_id):
        d = self._by_id.get(notification_id)
        if d:
            d["read_at"] = datetime.now(UTC)
            self._save()
            return copy.deepcopy(_notif_from_dict(d))
        raise KeyError(notification_id)

    def mark_all_read(self, user_id):
        now = datetime.now(UTC)
        for d in self._store.get(user_id, []):
            if d.get("read_at") is None:
                d["read_at"] = now
        self._save()

    def create(self, notification: Notification) -> Notification:
        nd = _notif_to_dict(notification)
        self._store.setdefault(notification.user_id, []).append(nd)
        self._by_id[notification.id] = nd
        self._save()
        return copy.deepcopy(notification)


# ---------------------------------------------------------------------------
# JsonDatabase — the public class referenced by session.py
# ---------------------------------------------------------------------------

class JsonDatabase:
    """
    JSON-file-backed database.

    Drop-in replacement for ``InMemoryDatabase``.  Change one line in
    ``api/db/session.py`` to switch::

        from .json_db import JsonDatabase
        _db = JsonDatabase()

    All 12 repository attributes have identical names and types so
    existing route handlers, services, and tests work without modification.

    Parameters
    ----------
    root : str | Path | None
        Project root directory (the one containing ``run.py``).
        Defaults to auto-detected root.

    Pipeline integration
    --------------------
    On startup, if ``<root>/model/functions.json`` exists (written by the
    document-generation pipeline), its contents **replace** the seeded
    function data.  This means the API automatically reflects the latest
    analysis run without any manual data migration.
    """

    def __init__(self, root: Optional[str | Path] = None):
        if root is None:
            root = _find_root()
        root = Path(root)
        data = _data_dir(root)
        model = _model_dir(root)

        # ------------------------------------------------------------------
        # Load or seed each collection
        # ------------------------------------------------------------------
        def _load_or_seed(filename: str, seed_key: str, seed: dict) -> dict:
            path = data / filename
            existing = _load_json(path)
            if not existing:
                _save_json(path, seed[seed_key])
                return seed[seed_key]
            return existing

        def _load_or_seed_list(filename: str, seed_key: str, seed: dict) -> dict:
            """For collections stored as {key: [list]} rather than {key: dict}."""
            path = data / filename
            existing = _load_json(path)
            if not existing:
                _save_json(path, seed[seed_key])
                return seed[seed_key]
            return existing

        seed = _default_seed()

        users_store     = _load_or_seed("users.json",           "users",           seed)
        projects_store  = _load_or_seed("projects.json",        "projects",        seed)
        members_store   = _load_or_seed("members.json",         "members",         seed)
        access_store    = _load_or_seed("access_requests.json", "access_requests", seed)
        versions_store  = _load_or_seed("versions.json",        "versions",        seed)
        commits_store   = _load_or_seed("commits.json",         "commits",         seed)
        jobs_store      = _load_or_seed("jobs.json",            "jobs",            seed)
        docs_store      = _load_or_seed("documents.json",       "documents",       seed)
        sections_store  = _load_or_seed_list("sections.json",   "sections",        seed)
        assigns_store   = _load_or_seed_list("assignments.json","assignments",     seed)
        fn_store        = _load_or_seed_list("functions.json",  "functions",       seed)
        notif_store     = _load_or_seed_list("notifications.json","notifications", seed)
        cmp_results     = _load_or_seed("compare_results.json", "compare_results", seed)
        cmp_diffs       = _load_or_seed_list("compare_diffs.json","compare_diffs", seed)

        # ------------------------------------------------------------------
        # Wire repositories
        # ------------------------------------------------------------------
        self.users:         IUserRepository               = _JsonUserRepo(users_store, data / "users.json")
        self.projects:      IProjectRepository            = _JsonProjectRepo(projects_store, members_store, data / "projects.json")
        self.members:       IProjectMemberRepository      = _JsonMemberRepo(members_store, data / "members.json")
        self.access_reqs:   IAccessRequestRepository      = _JsonAccessReqRepo(access_store, data / "access_requests.json")
        self.versions:      IVersionRepository            = _JsonVersionRepo(versions_store, data / "versions.json")
        self.commits:       ICommitRepository             = _JsonCommitRepo(commits_store, data / "commits.json")
        self.jobs:          IAnalysisJobRepository        = _JsonJobRepo(jobs_store, data / "jobs.json")
        self.documents:     IDocumentRepository           = _JsonDocRepo(docs_store, sections_store, data / "documents.json", data / "sections.json")
        self.assignments:   IDocumentAssignmentRepository = _JsonAssignRepo(assigns_store, data / "assignments.json")
        self._fn_repo       = _JsonFunctionRepo(fn_store, data / "functions.json")
        self.functions:     IFunctionRepository           = self._fn_repo
        self.compare:       ICompareRepository            = _JsonCompareRepo(cmp_results, cmp_diffs, data / "compare_results.json", data / "compare_diffs.json")
        self.notifications: INotificationRepository       = _JsonNotifRepo(notif_store, data / "notifications.json")

        # ------------------------------------------------------------------
        # Overlay pipeline output (model/functions.json) if it exists
        # ------------------------------------------------------------------
        pipeline_fns = _load_pipeline_functions(model)
        if pipeline_fns is not None:
            self._fn_repo.load_from_pipeline(pipeline_fns)
