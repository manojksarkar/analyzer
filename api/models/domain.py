"""
Domain models — plain dataclasses that represent the core entities.
No ORM annotations, no DB coupling.  All layers (services, routes) import
from here; the repository layer converts between these and its storage format.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums (plain strings — avoids Python enum verbosity while staying explicit)
# ---------------------------------------------------------------------------
# ComplianceStandard: "ISO_26262" | "ASPICE_L2" | "ASPICE_L3"
# RepoProvider:       "github" | "gitlab" | "bitbucket"
# ProjectStatus:      "not_run" | "running" | "in_review" | "complete" | "stale"
# MemberRole:         "admin" | "developer"
# MemberStatus:       "active" | "pending"
# VersionStatus:      "draft" | "in_review" | "approved"
# DocStatus:          "never" | "in_review" | "approved" | "unchanged"
# JobStatus:          "queued" | "running" | "paused" | "complete" | "failed" | "cancelled"
# PhaseStatus:        "pending" | "running" | "done" | "failed"
# Process:            "SYS.1" | "SYS.2" | "SWE.1" | "SWE.2" | "SWE.3"
# ReviewState:        "accepted" | "declined" | "edited" (or None)
# DiffType:           "added" | "changed" | "removed" | "unchanged"


@dataclass
class User:
    id: str
    email: str
    name: str
    initials: str
    avatar_url: Optional[str]
    hashed_password: str
    created_at: datetime


@dataclass
class Organization:
    id: str
    name: str
    tier: str          # "automotive_tier_1" | "tier_2" | "oem"
    created_at: datetime


@dataclass
class Project:
    id: str
    org_id: str
    name: str
    client: str
    compliance_standard: str
    repo_url: str
    repo_provider: str
    default_branch: str
    build_config: dict[str, Any]
    architecture_layers: list[dict[str, Any]]
    status: str
    created_by: str
    created_at: datetime
    updated_at: datetime


@dataclass
class ProjectMember:
    id: str
    project_id: str
    user_id: str
    role: str           # "admin" | "developer"
    status: str         # "active" | "pending"
    invited_by: str
    invited_at: datetime
    joined_at: Optional[datetime]


@dataclass
class AccessRequest:
    id: str
    project_id: str
    user_id: str
    requested_at: datetime
    status: str         # "pending" | "approved" | "denied"
    resolved_by: Optional[str]
    resolved_at: Optional[datetime]


@dataclass
class Version:
    id: str
    project_id: str
    tag: str
    commit_sha: str
    branch: str
    description: str
    status: str         # "draft" | "in_review" | "approved"
    docs_count: int
    created_by: str
    created_at: datetime


@dataclass
class Commit:
    sha: str
    project_id: str
    branch: str
    message: str
    author_name: str
    author_email: str
    committed_at: datetime
    has_version: bool
    version_id: Optional[str]
    doc_status: str     # "never" | "in_review" | "approved" | "complete"


@dataclass
class AnalysisPhase:
    number: int
    name: str
    status: str         # "pending" | "running" | "done" | "failed"
    duration_seconds: Optional[int]


@dataclass
class AnalysisJob:
    id: str
    project_id: str
    commit_sha: str
    version_id: Optional[str]
    reference_version_id: Optional[str]
    status: str
    pause_after_phase1: bool
    layer_filter: Optional[str]
    phase: int
    phase_pct: int
    current_activity: str
    activity_detail: str
    elapsed_seconds: int
    eta_seconds: Optional[int]
    phases: list[AnalysisPhase]
    started_at: datetime
    completed_at: Optional[datetime]
    error_message: Optional[str]
    branch: str = "main"
    version_tag: Optional[str] = None


@dataclass
class Document:
    id: str
    project_id: str
    version_id: str
    process: str        # "SYS.1" | "SYS.2" | "SWE.1" | "SWE.2" | "SWE.3"
    name: str
    subtitle: str
    layer: str
    group: str
    status: str         # "never" | "in_review" | "approved" | "unchanged"
    due_date: Optional[date]
    created_at: datetime
    updated_at: datetime


@dataclass
class DocumentSection:
    id: str
    document_id: str
    section_key: str    # "intro" | "interfaces" | "static_design" | "dynamic_design" | ...
    title: str
    order: int
    content: str
    review_state: Optional[str]   # "accepted" | "declined" | "edited" | None
    reviewed_by: Optional[str]
    reviewed_at: Optional[datetime]


@dataclass
class DocumentAssignment:
    id: str
    document_id: str
    user_id: str
    assigned_by: str
    assigned_at: datetime


@dataclass
class Function:
    id: str
    project_id: str
    version_id: str
    name: str
    file_path: str
    layer: str
    group: str
    is_visible: bool
    is_new: bool
    description: str


@dataclass
class CompareResult:
    id: str
    project_id: str
    current_version_id: str
    baseline_version_id: str
    diff_summary: dict[str, int]   # {"added": N, "changed": N, "removed": N, "unchanged": N}


@dataclass
class DocumentDiff:
    id: str
    compare_result_id: str
    document_id: str
    diff_type: str          # "added" | "changed" | "removed"
    sections_changed: list[str]


@dataclass
class Notification:
    id: str
    user_id: str
    project_id: str
    type: str
    message: str
    read_at: Optional[datetime]
    created_at: datetime
