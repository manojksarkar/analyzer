"""Mapper rename invariants (docs/production-redesign/07, PG-2).

The API parity suite already exercises these end-to-end, but the field<->column
renames are the kind of thing that regresses silently, so they get an explicit,
fast guard here: the domain field must land in the renamed column, and round-trip
back unchanged.
"""
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.unit

from api.db.postgres import schema as s
from api.db.postgres.mappers import to_row, from_row
from api.models.domain import (Version, Document, DocumentSection, AnalysisJob,
                               AnalysisPhase)

UTC = timezone.utc


def test_version_tag_maps_to_version_column():
    v = Version(id="v1", project_id="p1", tag="v1.2.0", commit_sha="abc", branch="main",
                description="", status="draft", docs_count=0, created_by="u1",
                created_at=datetime.now(UTC))
    row = to_row(v)
    assert "version" in row and row["version"] == "v1.2.0"
    assert "tag" not in row
    assert from_row(Version, row).tag == "v1.2.0"


def test_document_group_maps_to_component_column():
    d = Document(id="d1", project_id="p1", version_id="v1", process="SWE.3", name="X",
                 subtitle="", layer="L1", group="Core", status="in_review",
                 due_date=None, created_at=datetime.now(UTC), updated_at=datetime.now(UTC))
    row = to_row(d)
    assert row["component"] == "Core" and "group" not in row
    assert from_row(Document, row).group == "Core"


def test_section_order_maps_to_ord_column():
    sec = DocumentSection(id="s1", document_id="d1", section_key="intro", title="1", order=3,
                          content="body", review_state=None, reviewed_by=None, reviewed_at=None)
    row = to_row(sec)
    assert row["ord"] == 3 and "order" not in row
    assert from_row(DocumentSection, row).order == 3


def test_job_phases_serialize_to_json_and_back():
    job = AnalysisJob(
        id="j1", project_id="p1", commit_sha="abc", version_id=None, reference_version_id=None,
        status="queued", pause_after_phase1=False, layer_filter=None, phase=1, phase_pct=0,
        current_activity="", activity_detail="", elapsed_seconds=0, eta_seconds=None,
        phases=[AnalysisPhase(1, "Parse", "pending", None), AnalysisPhase(2, "Derive", "running", 5)],
        started_at=datetime.now(UTC), completed_at=None, error_message=None)
    row = to_row(job)
    assert isinstance(row["phases"], list) and isinstance(row["phases"][0], dict)  # JSON-ready
    back = from_row(AnalysisJob, row)
    assert [p.name for p in back.phases] == ["Parse", "Derive"]
    assert back.phases[1].duration_seconds == 5


def test_renamed_columns_exist_in_schema():
    assert "version" in s.versions.c and "tag" not in s.versions.c
    assert "component" in s.documents.c and "group" not in s.documents.c
    assert "ord" in s.document_sections.c and "order" not in s.document_sections.c
