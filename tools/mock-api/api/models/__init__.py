"""
Domain models — plain dataclasses with no ORM or DB dependency.
The DB layer maps to/from these; routes and services work only with these.
"""
from .domain import (
    User, Organization, Project, ProjectMember, Version, Commit,
    AnalysisJob, AnalysisPhase, Document, DocumentSection,
    DocumentAssignment, Function, CompareResult, DocumentDiff, Notification,
    AccessRequest,
)

__all__ = [
    "User", "Organization", "Project", "ProjectMember", "Version", "Commit",
    "AnalysisJob", "AnalysisPhase", "Document", "DocumentSection",
    "DocumentAssignment", "Function", "CompareResult", "DocumentDiff",
    "Notification", "AccessRequest",
]
