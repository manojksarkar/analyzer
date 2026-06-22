"""
In-memory database — the default (and currently only) storage adapter.

Seeded with realistic dummy data for an automotive ASPICE platform so the
API is fully usable without any real database.

To swap to a real DB:
  1. Implement every interface in api/repositories/interfaces.py
  2. Replace the `InMemoryDatabase` instance in api/db/session.py
  3. No other file needs to change.
"""
from __future__ import annotations

import copy
from datetime import datetime, date, timedelta, timezone
from typing import Optional
import uuid

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

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
_HASHED_PW = "$2b$12$fF8gBrCFb2LekRWV1WQSf.OaQwXqfBktl6yqy0D1.FiS6T44RwcDC"  # bcrypt(sha256("secret"))
UTC = timezone.utc
_NOW = datetime(2026, 6, 22, 12, 0, 0, tzinfo=UTC)


def _dt(days_ago: int = 0, **kw) -> datetime:
    return _NOW - timedelta(days=days_ago, **kw)


# ---------------------------------------------------------------------------
# Seed data
# ---------------------------------------------------------------------------
def _seed_users() -> dict[str, User]:
    users = [
        User("u1", "alice@aspice.dev", "Alice Müller",    "AM", None, _HASHED_PW, _dt(180)),
        User("u2", "bob@aspice.dev",   "Bob Kumar",       "BK", None, _HASHED_PW, _dt(160)),
        User("u3", "carol@aspice.dev", "Carol Schmidt",   "CS", None, _HASHED_PW, _dt(120)),
        User("u4", "dave@aspice.dev",  "Dave Patel",      "DP", None, _HASHED_PW, _dt(90)),
        User("u5", "eve@aspice.dev",   "Eve Johansson",   "EJ", None, _HASHED_PW, _dt(60)),
    ]
    return {u.id: u for u in users}


def _seed_projects() -> dict[str, Project]:
    projects = [
        Project(
            id="p1", org_id="org1",
            name="VCU Engine Firmware", client="BMW",
            compliance_standard="ISO_26262",
            repo_url="https://github.com/org/vcu-firmware",
            repo_provider="github", default_branch="main",
            build_config={"preprocessor_defs_file": None, "data_dictionary_file": None},
            architecture_layers=[
                {"name": "APP_LAYER",  "groups": ["Chassis_Mgmt", "Powertrain", "Body"]},
                {"name": "HAL_LAYER",  "groups": ["Drivers"]},
            ],
            status="in_review",
            created_by="u1", created_at=_dt(120), updated_at=_dt(7),
        ),
        Project(
            id="p2", org_id="org1",
            name="ADAS Sensor Fusion", client="Bosch",
            compliance_standard="ASPICE_L2",
            repo_url="https://github.com/org/adas-fusion",
            repo_provider="github", default_branch="develop",
            build_config={},
            architecture_layers=[
                {"name": "PERCEPTION", "groups": ["Camera", "Radar", "Lidar"]},
                {"name": "FUSION",     "groups": ["Kalman", "Occupancy"]},
            ],
            status="complete",
            created_by="u1", created_at=_dt(200), updated_at=_dt(3),
        ),
        Project(
            id="p3", org_id="org2",
            name="Gateway ECU", client="Continental",
            compliance_standard="ASPICE_L3",
            repo_url="https://github.com/org/gateway-ecu",
            repo_provider="github", default_branch="main",
            build_config={},
            architecture_layers=[
                {"name": "COMM_LAYER", "groups": ["CAN", "Ethernet", "LIN"]},
            ],
            status="not_run",
            created_by="u3", created_at=_dt(30), updated_at=_dt(30),
        ),
    ]
    return {p.id: p for p in projects}


def _seed_members() -> dict[str, ProjectMember]:
    members = [
        ProjectMember("m1", "p1", "u1", "admin",     "active",  "u1", _dt(120), _dt(119)),
        ProjectMember("m2", "p1", "u2", "developer", "active",  "u1", _dt(100), _dt(99)),
        ProjectMember("m3", "p1", "u3", "developer", "active",  "u1", _dt(100), _dt(98)),
        ProjectMember("m4", "p1", "u4", "developer", "pending", "u1", _dt(5),   None),
        ProjectMember("m5", "p2", "u1", "admin",     "active",  "u1", _dt(200), _dt(199)),
        ProjectMember("m6", "p2", "u5", "developer", "active",  "u1", _dt(190), _dt(188)),
        ProjectMember("m7", "p3", "u3", "admin",     "active",  "u3", _dt(30),  _dt(29)),
    ]
    return {m.id: m for m in members}


def _seed_versions() -> dict[str, Version]:
    versions = [
        Version("ver1", "p1", "v1.0.0", "a1b2c3d", "main", "Initial release",
                "approved", 15, "u1", _dt(90)),
        Version("ver2", "p1", "v1.1.0", "e4f5g6h", "main", "Brake system additions",
                "approved", 22, "u1", _dt(45)),
        Version("ver3", "p1", "v1.2.0", "b2e8d45", "main", "Powertrain refactor",
                "in_review", 30, "u1", _dt(7)),
        Version("ver4", "p2", "v2.0.0", "d9c8b7a", "develop", "Kalman filter upgrade",
                "approved", 12, "u5", _dt(20)),
    ]
    return {v.id: v for v in versions}


def _seed_commits() -> dict[str, Commit]:
    commits = [
        Commit("b2e8d45", "p1", "main", "feat: powertrain refactor",
               "Alice Müller", "alice@aspice.dev", _dt(7), True, "ver3", "in_review"),
        Commit("c1d2e3f", "p1", "main", "fix: brake override logic",
               "Bob Kumar",    "bob@aspice.dev",   _dt(9), False, None, "never"),
        Commit("e4f5g6h", "p1", "main", "feat: brake system FMEA table",
               "Alice Müller", "alice@aspice.dev", _dt(45), True, "ver2", "approved"),
        Commit("a1b2c3d", "p1", "main", "chore: initial commit",
               "Alice Müller", "alice@aspice.dev", _dt(90), True, "ver1", "approved"),
        Commit("abc1234", "p1", "main", "feat: add brake system FMEA table",
               "Manoj S.",     "manoj@aspice.dev", _dt(1), False, None, "never"),
        Commit("d9c8b7a", "p2", "develop", "feat: Kalman filter upgrade",
               "Eve Johansson","eve@aspice.dev",   _dt(20), True, "ver4", "approved"),
    ]
    return {f"{c.project_id}:{c.sha}": c for c in commits}


def _seed_jobs() -> dict[str, AnalysisJob]:
    phases_done = [
        AnalysisPhase(1, "Parse C++",    "done",    192),
        AnalysisPhase(2, "Derive Model", "running", None),
        AnalysisPhase(3, "Run Views",    "pending", None),
        AnalysisPhase(4, "Export DOCX",  "pending", None),
    ]
    phases_complete = [
        AnalysisPhase(1, "Parse C++",    "done", 180),
        AnalysisPhase(2, "Derive Model", "done", 720),
        AnalysisPhase(3, "Run Views",    "done", 360),
        AnalysisPhase(4, "Export DOCX",  "done", 120),
    ]
    jobs = [
        AnalysisJob(
            id="job1", project_id="p1", commit_sha="b2e8d45",
            version_id="ver3", reference_version_id="ver2",
            status="running", pause_after_phase1=False, layer_filter=None,
            phase=2, phase_pct=37,
            current_activity="Enriching function descriptions with LLM...",
            activity_detail="312 of 842 functions",
            elapsed_seconds=1872, eta_seconds=15600,
            phases=phases_done,
            started_at=_dt(0, hours=2), completed_at=None, error_message=None,
            branch="main",
        ),
        AnalysisJob(
            id="job2", project_id="p2", commit_sha="d9c8b7a",
            version_id="ver4", reference_version_id=None,
            status="complete", pause_after_phase1=False, layer_filter=None,
            phase=4, phase_pct=100,
            current_activity="Done",
            activity_detail="",
            elapsed_seconds=1380, eta_seconds=0,
            phases=phases_complete,
            started_at=_dt(20, hours=3), completed_at=_dt(20, hours=1), error_message=None,
            branch="develop",
        ),
    ]
    return {j.id: j for j in jobs}


def _seed_documents() -> dict[str, Document]:
    docs = []
    entries = [
        # (id, version_id, project_id, process, name, subtitle, layer, group, status)
        ("doc1",  "ver3", "p1", "SWE.3", "Brake Controller",        "Unit Design",    "APP_LAYER", "Chassis_Mgmt", "in_review"),
        ("doc2",  "ver3", "p1", "SWE.3", "Throttle Controller",     "Unit Design",    "APP_LAYER", "Powertrain",   "in_review"),
        ("doc3",  "ver3", "p1", "SWE.2", "Chassis Management",      "Component Design","APP_LAYER","Chassis_Mgmt", "never"),
        ("doc4",  "ver3", "p1", "SWE.1", "Software Requirements",   "SRS",            "APP_LAYER", "Global",       "approved"),
        ("doc5",  "ver3", "p1", "SYS.2", "System Requirements",     "SyRS",           "APP_LAYER", "Global",       "approved"),
        ("doc6",  "ver3", "p1", "SWE.3", "Body Control Module",     "Unit Design",    "APP_LAYER", "Body",         "unchanged"),
        ("doc7",  "ver2", "p1", "SWE.3", "Brake Controller",        "Unit Design",    "APP_LAYER", "Chassis_Mgmt", "approved"),
        ("doc8",  "ver4", "p2", "SWE.3", "Kalman Filter Core",      "Unit Design",    "FUSION",    "Kalman",       "approved"),
    ]
    for e in entries:
        docs.append(Document(
            id=e[0], project_id=e[2], version_id=e[1],
            process=e[3], name=e[4], subtitle=e[5],
            layer=e[6], group=e[7], status=e[8],
            due_date=date(2026, 7, 1) if e[8] == "in_review" else None,
            created_at=_dt(10), updated_at=_dt(2),
        ))
    return {d.id: d for d in docs}


def _seed_sections() -> dict[str, list[DocumentSection]]:
    sections_map: dict[str, list[DocumentSection]] = {}
    # doc1 — Brake Controller (SWE.3) — in_review
    sections_map["doc1"] = [
        DocumentSection("sec1_1", "doc1", "intro", "1. Introduction", 1,
            "The Brake Controller unit implements the primary braking logic for the "
            "VCU Engine Firmware. It receives driver pedal inputs and wheel-speed "
            "sensor data, computes the optimal brake torque distribution, and issues "
            "commands to the individual wheel actuators.",
            "accepted", "u2", _dt(1)),
        DocumentSection("sec1_2", "doc1", "interfaces", "2. Interfaces", 2,
            "| ID | Direction | Type | Description |\n"
            "|---|---|---|---|\n"
            "| IF_PedalPos | Input | float32 | Brake pedal position 0-100% |\n"
            "| IF_WheelSpd | Input | float32[4] | Individual wheel speeds in rpm |\n"
            "| IF_DiagStatus | Output | uint32 | Diagnostic trouble code bitmask |",
            "declined", "u2", _dt(1)),
        DocumentSection("sec1_3", "doc1", "static_design", "3. Static Design", 3,
            "The module is structured as a single cyclic runnable `BrakeCtrl_Run` "
            "executing at 10 ms. Internal state is maintained in a static struct "
            "`BrakeCtrl_State_t` holding slip-ratio accumulators and PID integrators.",
            None, None, None),
        DocumentSection("sec1_4", "doc1", "dynamic_design", "4. Dynamic Design", 4,
            "On each cycle: (1) read inputs, (2) compute slip ratios, "
            "(3) run PID controller, (4) clamp output to actuator limits, "
            "(5) write outputs and update diagnostics.",
            None, None, None),
    ]
    # doc2 — Throttle Controller (SWE.3) — in_review
    sections_map["doc2"] = [
        DocumentSection("sec2_1", "doc2", "intro", "1. Introduction", 1,
            "The Throttle Controller manages the electronic throttle body, "
            "translating accelerator pedal position into throttle plate angle "
            "with torque-demand arbitration from cruise control and traction control.",
            "accepted", "u3", _dt(2)),
        DocumentSection("sec2_2", "doc2", "interfaces", "2. Interfaces", 2,
            "| ID | Direction | Type | Description |\n"
            "|---|---|---|---|\n"
            "| IF_AccelPos | Input | float32 | Accelerator pedal 0-100% |\n"
            "| IF_ThrottleCmd | Output | float32 | Throttle plate angle 0-90° |",
            None, None, None),
        DocumentSection("sec2_3", "doc2", "static_design", "3. Static Design", 3,
            "Single runnable `ThrottleCtrl_Run` at 10 ms. PID gains stored in NVM.",
            None, None, None),
    ]
    # doc4 — Software Requirements (SWE.1)
    sections_map["doc4"] = [
        DocumentSection("sec4_1", "doc4", "intro", "1. Introduction", 1,
            "This document captures all software-level requirements derived from "
            "the system requirements for the VCU Engine Firmware v1.2.0.",
            "accepted", "u1", _dt(5)),
        DocumentSection("sec4_2", "doc4", "requirements", "2. Requirements", 2,
            "SWE-REQ-001: The system shall respond to brake pedal input within 10 ms.\n"
            "SWE-REQ-002: The throttle shall not exceed 90° under any fault condition.\n"
            "SWE-REQ-003: Diagnostic codes shall be updated within one control cycle.",
            "accepted", "u1", _dt(5)),
    ]
    return sections_map


def _seed_assignments() -> dict[str, list[DocumentAssignment]]:
    return {
        "doc1": [
            DocumentAssignment("asgn1", "doc1", "u2", "u1", _dt(5)),
            DocumentAssignment("asgn2", "doc1", "u3", "u1", _dt(5)),
        ],
        "doc2": [
            DocumentAssignment("asgn3", "doc2", "u3", "u1", _dt(4)),
        ],
    }


def _seed_functions() -> dict[str, list[Function]]:
    fns = [
        Function("f1", "p1", "ver3", "BrakeCtrl_Run",        "Layer1/Chassis_Mgmt/brake_ctrl.c",    "APP_LAYER", "Chassis_Mgmt", True,  True,  "Main cyclic execution of brake control logic"),
        Function("f2", "p1", "ver3", "BrakeCtrl_Init",       "Layer1/Chassis_Mgmt/brake_ctrl.c",    "APP_LAYER", "Chassis_Mgmt", True,  False, "Initialises brake controller state to safe defaults"),
        Function("f3", "p1", "ver3", "BrakeCtrl_SetGains",   "Layer1/Chassis_Mgmt/brake_ctrl.c",    "APP_LAYER", "Chassis_Mgmt", False, False, "Writes PID gains from NVM calibration"),
        Function("f4", "p1", "ver3", "ThrottleCtrl_Run",     "Layer1/Powertrain/throttle_ctrl.c",   "APP_LAYER", "Powertrain",   True,  True,  "Main cyclic execution of throttle control logic"),
        Function("f5", "p1", "ver3", "ThrottleCtrl_Init",    "Layer1/Powertrain/throttle_ctrl.c",   "APP_LAYER", "Powertrain",   True,  False, "Initialises throttle controller"),
        Function("f6", "p1", "ver3", "BodyCtrl_LightRun",    "Layer1/Body/body_ctrl.c",             "APP_LAYER", "Body",         True,  False, "Manages exterior lighting state machine"),
        Function("f7", "p1", "ver3", "HAL_ADC_Read",         "Layer2/Drivers/hal_adc.c",            "HAL_LAYER", "Drivers",      True,  False, "Reads ADC channel and returns raw 12-bit value"),
        Function("f8", "p1", "ver3", "HAL_ADC_Init",         "Layer2/Drivers/hal_adc.c",            "HAL_LAYER", "Drivers",      True,  False, "Configures ADC peripheral"),
    ]
    # index by job_id (job1 → ver3 functions)
    return {"job1": fns}


def _seed_notifications() -> dict[str, list[Notification]]:
    notifs = [
        Notification("n1", "u2", "p1", "review_requested",
                     "You have been assigned to review Brake Controller (v1.2.0).",
                     None, _dt(5)),
        Notification("n2", "u3", "p1", "review_requested",
                     "You have been assigned to review Throttle Controller (v1.2.0).",
                     None, _dt(4)),
        Notification("n3", "u1", "p1", "job_complete",
                     "Analysis job for commit b2e8d45 completed successfully.",
                     _dt(8), _dt(8)),
    ]
    by_user: dict[str, list[Notification]] = {}
    for n in notifs:
        by_user.setdefault(n.user_id, []).append(n)
    return by_user


def _seed_compare() -> tuple[dict[str, CompareResult], dict[str, list[DocumentDiff]]]:
    cr = CompareResult(
        "cmp1", "p1", "ver3", "ver2",
        {"added": 1, "changed": 1, "removed": 0, "unchanged": 4},
    )
    diffs = [
        DocumentDiff("diff1", "cmp1", "doc1", "changed", ["interfaces", "dynamic_design"]),
        DocumentDiff("diff2", "cmp1", "doc2", "added",   []),
    ]
    return {"cmp1": cr}, {"cmp1": diffs}


# ---------------------------------------------------------------------------
# Concrete in-memory repository implementations
# ---------------------------------------------------------------------------

class _InMemUserRepo(IUserRepository):
    def __init__(self, store: dict[str, User]):
        self._store = store
        self._by_email = {u.email: u for u in store.values()}

    def get_by_id(self, user_id):
        return copy.deepcopy(self._store.get(user_id))

    def get_by_email(self, email):
        u = self._by_email.get(email)
        return copy.deepcopy(u)

    def create(self, user):
        self._store[user.id] = user
        self._by_email[user.email] = user
        return copy.deepcopy(user)

    def update(self, user):
        self._store[user.id] = user
        self._by_email[user.email] = user
        return copy.deepcopy(user)

    def list_by_ids(self, ids):
        return [copy.deepcopy(self._store[i]) for i in ids if i in self._store]


class _InMemProjectRepo(IProjectRepository):
    def __init__(self, store: dict[str, Project], members: dict[str, ProjectMember]):
        self._store = store
        self._members = members

    def list_for_user(self, user_id):
        project_ids = {
            m.project_id for m in self._members.values()
            if m.user_id == user_id and m.status == "active"
        }
        return [copy.deepcopy(p) for p in self._store.values() if p.id in project_ids]

    def get(self, project_id):
        return copy.deepcopy(self._store.get(project_id))

    def create(self, project):
        self._store[project.id] = project
        return copy.deepcopy(project)

    def update(self, project):
        self._store[project.id] = project
        return copy.deepcopy(project)

    def delete(self, project_id):
        self._store.pop(project_id, None)

    def search(self, query):
        q = query.lower()
        return [
            copy.deepcopy(p) for p in self._store.values()
            if q in p.name.lower() or q in p.client.lower()
        ]


class _InMemMemberRepo(IProjectMemberRepository):
    def __init__(self, store: dict[str, ProjectMember]):
        self._store = store

    def _project_members(self, project_id):
        return [m for m in self._store.values() if m.project_id == project_id]

    def list_members(self, project_id):
        return [copy.deepcopy(m) for m in self._project_members(project_id) if m.status == "active"]

    def get_member(self, project_id, user_id):
        for m in self._project_members(project_id):
            if m.user_id == user_id:
                return copy.deepcopy(m)
        return None

    def add_member(self, member):
        self._store[member.id] = member
        return copy.deepcopy(member)

    def update_member(self, member):
        self._store[member.id] = member
        return copy.deepcopy(member)

    def remove_member(self, project_id, user_id):
        to_del = [k for k, m in self._store.items()
                  if m.project_id == project_id and m.user_id == user_id]
        for k in to_del:
            del self._store[k]

    def list_pending(self, project_id):
        return [copy.deepcopy(m) for m in self._project_members(project_id) if m.status == "pending"]

    def cancel_invite(self, project_id, invite_id):
        self._store.pop(invite_id, None)


class _InMemAccessReqRepo(IAccessRequestRepository):
    def __init__(self):
        self._store: dict[str, AccessRequest] = {}

    def create(self, req):
        self._store[req.id] = req
        return copy.deepcopy(req)

    def list_pending(self, project_id):
        return [copy.deepcopy(r) for r in self._store.values()
                if r.project_id == project_id and r.status == "pending"]

    def get(self, req_id):
        return copy.deepcopy(self._store.get(req_id))

    def update(self, req):
        self._store[req.id] = req
        return copy.deepcopy(req)


class _InMemVersionRepo(IVersionRepository):
    def __init__(self, store: dict[str, Version]):
        self._store = store

    def list_for_project(self, project_id):
        return [copy.deepcopy(v) for v in self._store.values() if v.project_id == project_id]

    def get(self, version_id):
        return copy.deepcopy(self._store.get(version_id))

    def create(self, version):
        self._store[version.id] = version
        return copy.deepcopy(version)

    def update(self, version):
        self._store[version.id] = version
        return copy.deepcopy(version)

    def delete(self, version_id):
        self._store.pop(version_id, None)

    def get_by_tag(self, project_id, tag):
        for v in self._store.values():
            if v.project_id == project_id and v.tag == tag:
                return copy.deepcopy(v)
        return None


class _InMemCommitRepo(ICommitRepository):
    def __init__(self, store: dict[str, Commit]):
        self._store = store   # key: "project_id:sha"

    def list_for_project(self, project_id, page=1, per_page=20):
        items = [
            copy.deepcopy(c) for c in self._store.values()
            if c.project_id == project_id
        ]
        items.sort(key=lambda c: c.committed_at, reverse=True)
        total = len(items)
        start = (page - 1) * per_page
        return items[start:start + per_page], total

    def get(self, project_id, sha):
        return copy.deepcopy(self._store.get(f"{project_id}:{sha}"))

    def upsert(self, commit):
        self._store[f"{commit.project_id}:{commit.sha}"] = commit
        return copy.deepcopy(commit)


class _InMemJobRepo(IAnalysisJobRepository):
    def __init__(self, store: dict[str, AnalysisJob]):
        self._store = store

    def create(self, job):
        self._store[job.id] = job
        return copy.deepcopy(job)

    def get(self, job_id):
        return copy.deepcopy(self._store.get(job_id))

    def get_current(self, project_id):
        # Latest non-cancelled job for the project
        candidates = [
            j for j in self._store.values()
            if j.project_id == project_id and j.status not in ("cancelled",)
        ]
        if not candidates:
            return None
        return copy.deepcopy(max(candidates, key=lambda j: j.started_at))

    def update(self, job):
        self._store[job.id] = job
        return copy.deepcopy(job)


class _InMemDocRepo(IDocumentRepository):
    def __init__(
        self,
        store: dict[str, Document],
        sections: dict[str, list[DocumentSection]],
    ):
        self._store = store
        self._sections = sections   # doc_id → [DocumentSection]

    def list_for_project(self, project_id, version_id=None, process=None,
                         status=None, assignee_id=None, query=None, page=1, per_page=20):
        items = [d for d in self._store.values() if d.project_id == project_id]
        if version_id:
            items = [d for d in items if d.version_id == version_id]
        if process:
            items = [d for d in items if d.process == process]
        if status:
            items = [d for d in items if d.status == status]
        if query:
            q = query.lower()
            items = [d for d in items if q in d.name.lower()]
        total = len(items)
        start = (page - 1) * per_page
        return [copy.deepcopy(d) for d in items[start:start + per_page]], total

    def get(self, document_id):
        return copy.deepcopy(self._store.get(document_id))

    def update(self, document):
        self._store[document.id] = document
        return copy.deepcopy(document)

    def get_stats(self, project_id, version_id=None):
        items = [d for d in self._store.values() if d.project_id == project_id]
        if version_id:
            items = [d for d in items if d.version_id == version_id]
        stats: dict[str, int] = {"total": 0, "approved": 0, "in_review": 0, "never": 0, "unchanged": 0}
        for d in items:
            stats["total"] += 1
            stats[d.status] = stats.get(d.status, 0) + 1
        return stats

    def list_sections(self, document_id):
        secs = self._sections.get(document_id, [])
        return [copy.deepcopy(s) for s in sorted(secs, key=lambda s: s.order)]

    def get_section(self, document_id, section_key):
        for s in self._sections.get(document_id, []):
            if s.section_key == section_key:
                return copy.deepcopy(s)
        return None

    def update_section(self, section):
        secs = self._sections.setdefault(section.document_id, [])
        for i, s in enumerate(secs):
            if s.section_key == section.section_key:
                secs[i] = section
                return copy.deepcopy(section)
        secs.append(section)
        return copy.deepcopy(section)


class _InMemAssignRepo(IDocumentAssignmentRepository):
    def __init__(self, store: dict[str, list[DocumentAssignment]]):
        self._store = store  # doc_id → [DocumentAssignment]

    def list_for_document(self, document_id):
        return [copy.deepcopy(a) for a in self._store.get(document_id, [])]

    def assign(self, assignment):
        lst = self._store.setdefault(assignment.document_id, [])
        lst.append(assignment)
        return copy.deepcopy(assignment)

    def remove(self, document_id, user_id):
        self._store[document_id] = [
            a for a in self._store.get(document_id, []) if a.user_id != user_id
        ]

    def batch_assign(self, assignments):
        for a in assignments:
            self.assign(a)


class _InMemFunctionRepo(IFunctionRepository):
    def __init__(self, store: dict[str, list[Function]]):
        self._store = store      # job_id → [Function]
        self._by_id: dict[str, Function] = {
            f.id: f for fns in store.values() for f in fns
        }

    def list_for_job(self, job_id):
        return [copy.deepcopy(f) for f in self._store.get(job_id, [])]

    def get(self, function_id):
        return copy.deepcopy(self._by_id.get(function_id))

    def update(self, function):
        self._by_id[function.id] = function
        for job_id, fns in self._store.items():
            for i, f in enumerate(fns):
                if f.id == function.id:
                    fns[i] = function
        return copy.deepcopy(function)

    def bulk_update_visibility(self, function_ids, is_visible):
        for fid in function_ids:
            f = self._by_id.get(fid)
            if f:
                f.is_visible = is_visible
                self.update(f)


class _InMemCompareRepo(ICompareRepository):
    def __init__(
        self,
        results: dict[str, CompareResult],
        diffs: dict[str, list[DocumentDiff]],
    ):
        self._results = results
        self._diffs = diffs

    def get_or_create(self, project_id, current_ref, baseline_ref):
        for cr in self._results.values():
            if cr.project_id == project_id:
                return copy.deepcopy(cr)
        # Create a blank one
        cr = CompareResult(
            str(uuid.uuid4()), project_id, current_ref, baseline_ref,
            {"added": 0, "changed": 0, "removed": 0, "unchanged": 0},
        )
        self._results[cr.id] = cr
        return copy.deepcopy(cr)

    def list_diffs(self, compare_id):
        return [copy.deepcopy(d) for d in self._diffs.get(compare_id, [])]

    def get_document_diff(self, compare_id, document_id):
        for d in self._diffs.get(compare_id, []):
            if d.document_id == document_id:
                return copy.deepcopy(d)
        return None


class _InMemNotifRepo(INotificationRepository):
    def __init__(self, store: dict[str, list[Notification]]):
        self._store = store   # user_id → [Notification]
        self._by_id: dict[str, Notification] = {
            n.id: n for ns in store.values() for n in ns
        }

    def list_unread(self, user_id):
        return [
            copy.deepcopy(n)
            for n in self._store.get(user_id, [])
            if n.read_at is None
        ]

    def mark_read(self, notification_id):
        n = self._by_id.get(notification_id)
        if n:
            n.read_at = datetime.now(UTC)
            return copy.deepcopy(n)
        raise KeyError(notification_id)

    def mark_all_read(self, user_id):
        now = datetime.now(UTC)
        for n in self._store.get(user_id, []):
            if n.read_at is None:
                n.read_at = now

    def create(self, notification):
        self._store.setdefault(notification.user_id, []).append(notification)
        self._by_id[notification.id] = notification
        return copy.deepcopy(notification)


# ---------------------------------------------------------------------------
# Database — single object that wires all repositories together
# ---------------------------------------------------------------------------

class InMemoryDatabase:
    """
    The in-memory database.  Exposes one repository per aggregate root.

    To replace with a real DB:
      1. Create a new class (e.g. `PostgresDatabase`) that holds the
         same set of repository attributes.
      2. Replace `_db` in `api/db/session.py`.
      No other files need changing.
    """

    def __init__(self):
        # seed raw stores
        users     = _seed_users()
        projects  = _seed_projects()
        members   = _seed_members()
        versions  = _seed_versions()
        commits   = _seed_commits()
        jobs      = _seed_jobs()
        docs      = _seed_documents()
        sections  = _seed_sections()
        assigns   = _seed_assignments()
        functions = _seed_functions()
        notifs    = _seed_notifications()
        cmp_results, cmp_diffs = _seed_compare()

        # wire repositories
        self.users:        IUserRepository               = _InMemUserRepo(users)
        self.projects:     IProjectRepository            = _InMemProjectRepo(projects, members)
        self.members:      IProjectMemberRepository      = _InMemMemberRepo(members)
        self.access_reqs:  IAccessRequestRepository      = _InMemAccessReqRepo()
        self.versions:     IVersionRepository            = _InMemVersionRepo(versions)
        self.commits:      ICommitRepository             = _InMemCommitRepo(commits)
        self.jobs:         IAnalysisJobRepository        = _InMemJobRepo(jobs)
        self.documents:    IDocumentRepository           = _InMemDocRepo(docs, sections)
        self.assignments:  IDocumentAssignmentRepository = _InMemAssignRepo(assigns)
        self.functions:    IFunctionRepository           = _InMemFunctionRepo(functions)
        self.compare:      ICompareRepository            = _InMemCompareRepo(cmp_results, cmp_diffs)
        self.notifications: INotificationRepository      = _InMemNotifRepo(notifs)
