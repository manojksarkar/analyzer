"""The database schema — single source of truth (docs/production-redesign/07 §4).

SQLAlchemy Core `Table` objects in one `metadata`. Design highlights:

* **Manifest-of-pointers storage (D-9).** A version does NOT copy the model. Stable
  identity lives in `entities`; each version contributes one thin row per entity in
  `entity_versions`; the heavy/variable payload lives once in `content_blobs`,
  content-addressed. Carry-forward is "point at the same content_hash" — no copying —
  so storage grows with *distinct content*, not versions x entities.

* **Three hashes, three jobs (D-15).** `source_hash` (did the code change? -> classify),
  `fingerprint` (can I reuse the LLM output? -> reuse_index), `content_hash` (is this
  payload byte-identical to one already stored? -> dedup).

* **JSONB for nested/variable fields** (02 §4.1); typed columns only for what queries
  filter on. `_JSONB` degrades to generic JSON off-postgres so the schema builds on
  SQLite for structural tests without a live database.

* **Version identity (D-3).** `versions.version` is UI-supplied and UNIQUE per project.

Hashes are stored as hex `String` (not bytea): the codebase already produces hex
digests, and text keys are debuggable and join cleanly.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON, BigInteger, Boolean, Column, Date, DateTime, ForeignKey, Index,
    Integer, MetaData, String, Table, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()

# JSONB on Postgres; plain JSON elsewhere (SQLite structural tests).
_JSONB = JSON().with_variant(JSONB(), "postgresql")

# Auto-incrementing surrogate key. BIGINT on Postgres, but INTEGER on SQLite because
# SQLite only makes an exact `INTEGER PRIMARY KEY` the auto-incrementing rowid alias
# (a BIGINT PK would insert NULL). Lets the FK-strict SQLite tests exercise it.
_BIGID = BigInteger().with_variant(Integer, "sqlite")


def _ts(name: str, **kw) -> Column:
    """A timezone-aware timestamp column."""
    return Column(name, DateTime(timezone=True), **kw)


# ---------------------------------------------------------------------------
# G1 — Access  (RBAC kept as-is per D-8; only `organizations` was dropped)
# ---------------------------------------------------------------------------
users = Table(
    "users", metadata,
    Column("id", String, primary_key=True),
    Column("email", String, nullable=False, unique=True),
    Column("name", String, nullable=False),
    Column("initials", String),
    Column("avatar_url", String),
    Column("hashed_password", String, nullable=False),
    _ts("created_at", nullable=False),
)

projects = Table(
    "projects", metadata,
    Column("id", String, primary_key=True),
    # A free-text tenant tag. The `organizations` TABLE is dropped (D-8) but the
    # column stays a plain string so the domain dataclass + routes are untouched.
    Column("org_id", String),
    Column("name", String, nullable=False),
    Column("client", String),
    Column("compliance_standard", String),
    Column("repo_url", String),
    Column("repo_provider", String),
    Column("default_branch", String),
    Column("build_config", _JSONB),
    Column("architecture_layers", _JSONB),
    Column("status", String),
    Column("created_by", String),       # actor id/label ("system" appears) - not a FK
    _ts("created_at", nullable=False),
    _ts("updated_at"),
    _ts("last_commit_sync_at"),
)

project_members = Table(
    "project_members", metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("role", String),        # kept (D-8): migrate existing RBAC unchanged
    Column("status", String),
    Column("invited_by", String),
    _ts("invited_at"),
    _ts("joined_at"),
    UniqueConstraint("project_id", "user_id", name="uq_member_project_user"),
)

access_requests = Table(
    "access_requests", metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    _ts("requested_at"),
    Column("status", String),
    Column("resolved_by", String),
    _ts("resolved_at"),
)

# ---------------------------------------------------------------------------
# G3 — Commits & Versions
# ---------------------------------------------------------------------------
commits = Table(
    "commits", metadata,
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("sha", String, nullable=False),
    Column("branch", String),
    Column("message", Text),
    Column("author_name", String),
    Column("author_email", String),
    _ts("committed_at"),
    Column("has_version", Boolean, default=False),
    Column("version_id", String),
    Column("doc_status", String),
    UniqueConstraint("project_id", "sha", name="pk_commits"),
    Index("ix_commits_project", "project_id"),
)

versions = Table(
    "versions", metadata,
    Column("id", String, primary_key=True),                      # surrogate FK target
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("version", String, nullable=False),                   # D-3: UI-supplied identity
    Column("commit_sha", String),
    Column("branch", String),
    Column("description", Text),
    Column("status", String),                                    # review status: draft|in_review|approved
    Column("pipeline_status", String),                           # D-17: parsing|deriving|...|complete|failed
    Column("docs_count", Integer, default=0),
    Column("created_by", String),
    _ts("created_at", nullable=False),
    Column("baseline_version_id", String, ForeignKey("versions.id")),   # incremental baseline (self-ref)
    Column("decision", String),                                  # incremental|full
    Column("regenerated", Integer),
    Column("reused", Integer),
    Column("base_path", String),                                 # was metadata.json
    Column("project_name", String),
    Column("parse_fingerprint", String),                         # clang-flag guard (narrowed parse)
    Column("resolved_config", _JSONB),                           # was versions/<id>/config.json
    # The run manifest + end-of-run report, verbatim (doc 09, C1 follow-up). The named
    # columns above stay the queryable accounting; this is everything else the manifest
    # carries and no column covers — warnings, carriedForward, crossVersionReused,
    # documents. Without it, versions/<ver>/manifest.json is not redundant and cannot be
    # dropped: an operator on another node simply cannot see why a run warned.
    Column("run_report", _JSONB),                                # was versions/<id>/manifest.json
    Column("report", Text),                                      # was report.txt
    UniqueConstraint("project_id", "version", name="uq_version_project_version"),
)

# Phase-3 VIEW outputs (PG-5a) — the text/JSON files under versions/<ver…>/output/: interface
# tables, flowchart + unit-diagram mermaid, behaviour rows. Persisted so the API (doc render +
# compare) can read the views from Postgres instead of on-disk snapshots. PNG/DOCX binaries stay
# as files (D-14). One row per output file; composite PK (version_id, rel_path).
version_output_files = Table(
    "version_output_files", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), primary_key=True),
    Column("rel_path", String, primary_key=True),   # POSIX path under output/ (e.g. "My-Sample/interface_tables.json")
    Column("content", Text, nullable=False),         # the text/JSON file content
    Column("group_name", String),                    # top-level output subdir (component group) for filtered reads
)

# ---------------------------------------------------------------------------
# G2 — Operations
# ---------------------------------------------------------------------------
analysis_jobs = Table(
    "analysis_jobs", metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("version_id", String, ForeignKey("versions.id")),
    Column("commit_sha", String),
    Column("branch", String),
    Column("reference_version_id", String),
    Column("status", String),
    Column("pause_after_phase1", Boolean, default=False),
    Column("layer_filter", String),
    Column("phase", Integer),
    Column("phase_pct", Integer),
    Column("current_activity", String),
    Column("activity_detail", Text),
    Column("elapsed_seconds", Integer),
    Column("eta_seconds", Integer),
    Column("phases", _JSONB),                                    # list[AnalysisPhase]
    _ts("started_at"),
    _ts("completed_at"),
    Column("error_message", Text),
    Column("version_tag", String),                              # wire-compat alias of version
    Column("mode", String),
    Column("decision", String),
    Column("baseline_commit", String),
    Column("scope", _JSONB),
    Column("no_llm", Boolean, default=False),
    Column("data_dict_id", String),
    Column("narrowed_parse", Boolean, default=False),
    Column("regenerated", Integer),
    Column("reused", Integer),
    Index("ix_jobs_project", "project_id"),
)

notifications = Table(
    "notifications", metadata,
    Column("id", String, primary_key=True),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE")),
    Column("type", String),
    Column("message", Text),
    _ts("read_at"),
    _ts("created_at"),
    Index("ix_notifications_user", "user_id"),
)

# ---------------------------------------------------------------------------
# G4 — Documents
# ---------------------------------------------------------------------------
documents = Table(
    "documents", metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("process", String),
    Column("name", String),
    Column("subtitle", String),
    Column("layer", String),
    Column("component", String),        # domain field is `group` (a SQL reserved word)
    Column("status", String),
    Column("due_date", Date),
    Column("docx_path", String),        # artifact stays on disk; DB keeps the path
    _ts("created_at"),
    _ts("updated_at"),
    Index("ix_documents_version", "version_id"),
)

document_sections = Table(
    "document_sections", metadata,
    Column("id", String, primary_key=True),
    Column("document_id", String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    Column("section_key", String),
    Column("title", String),
    Column("ord", Integer),             # domain field is `order` (reserved)
    Column("content", Text),
    Column("review_state", String),
    Column("reviewed_by", String),
    _ts("reviewed_at"),
)

document_assignments = Table(
    "document_assignments", metadata,
    Column("id", String, primary_key=True),
    Column("document_id", String, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", String, ForeignKey("users.id"), nullable=False),
    Column("assigned_by", String),
    _ts("assigned_at"),
)

compare_results = Table(
    "compare_results", metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("current_version_id", String, ForeignKey("versions.id")),
    Column("baseline_version_id", String, ForeignKey("versions.id")),
    Column("diff_summary", _JSONB),
)

document_diffs = Table(
    "document_diffs", metadata,
    Column("id", String, primary_key=True),
    Column("compare_result_id", String, ForeignKey("compare_results.id", ondelete="CASCADE"), nullable=False),
    Column("document_id", String, ForeignKey("documents.id")),
    Column("diff_type", String),
    Column("sections_changed", _JSONB),
)

# ---------------------------------------------------------------------------
# G5 — Model (manifest of pointers, D-9)
# ---------------------------------------------------------------------------
content_blobs = Table(
    "content_blobs", metadata,
    Column("content_hash", String, primary_key=True),           # stored once, content-addressed
    Column("kind", String),                                     # function|global|type|summary|mermaid
    Column("payload", _JSONB, nullable=False),
)

entities = Table(
    "entities", metadata,
    Column("entity_id", _BIGID, primary_key=True, autoincrement=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("entity_key", String, nullable=False),               # Component|Unit|qname|params
    Column("kind", String, nullable=False),                     # function|global|type|macro
    Column("qualified_name", String),
    UniqueConstraint("project_id", "entity_key", name="uq_entity_project_key"),
)

entity_versions = Table(
    "entity_versions", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("entity_id", BigInteger, ForeignKey("entities.entity_id"), nullable=False),
    # thin structural columns — what interface tables / diagrams filter on
    Column("component", String),
    Column("unit", String),
    Column("file", String),
    Column("line", Integer),
    Column("end_line", Integer),
    Column("direction", String),
    Column("direction_reason", String),
    Column("visibility", String),
    Column("interface_id", String),
    Column("is_visible", Boolean, default=True),                # hide/unhide; carries forward (D-18)
    # the three hashes (D-15)
    Column("source_hash", String),                             # code changed? -> classify
    Column("fingerprint", String),                             # reuse LLM output? -> reuse_index
    Column("content_hash", String, ForeignKey("content_blobs.content_hash")),   # payload pointer
    UniqueConstraint("version_id", "entity_id", name="pk_entity_versions"),
    Index("ix_ev_version", "version_id"),
    Index("ix_ev_version_component", "version_id", "component"),
)

model_units = Table(
    "model_units", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("unit_key", String, nullable=False),                 # Component|Unit
    Column("component", String),
    Column("name", String),
    Column("path", String),
    Column("file_name", String),
    Column("included_headers", _JSONB),   # parser-specific (direct includes) - not derivable
    UniqueConstraint("version_id", "unit_key", name="pk_model_units"),
    # function/global/caller/callee lists DROPPED (D-13) — derived from entity_versions / model_edges
)

model_components = Table(
    "model_components", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("name", String, nullable=False),
    Column("header_files", _JSONB),                             # used by the unit-header table
    UniqueConstraint("version_id", "name", name="pk_model_components"),
)

model_summaries = Table(
    "model_summaries", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("scope", String, nullable=False),                    # file|component|project
    Column("key", String, nullable=False),
    Column("text_hash", String, ForeignKey("content_blobs.content_hash")),   # deduped text
    UniqueConstraint("version_id", "scope", "key", name="pk_model_summaries"),
)

# The API's slim per-job function view (id/name/file/visibility/is_new/description),
# written by the pipeline runner and read by the functions/hide-unhide endpoints.
# Distinct from the rich model (entities/entity_versions): PG-5 may re-express this as
# a view over entity_versions, but keeping it explicit now preserves current behaviour
# exactly. `job_id` is a storage key, not a `Function` domain field.
job_functions = Table(
    "job_functions", metadata,
    Column("id", String, primary_key=True),
    Column("job_id", String, nullable=False),
    Column("project_id", String),
    Column("version_id", String),
    Column("name", String),
    Column("file_path", String),
    Column("layer", String),
    Column("component", String),        # domain field is `group` (reserved)
    Column("is_visible", Boolean, default=True),
    Column("is_new", Boolean, default=False),
    Column("description", Text),
    Index("ix_job_functions_job", "job_id"),
)

# ---------------------------------------------------------------------------
# G6 — Dependency graph (one table; reverse index = impact analysis)
# ---------------------------------------------------------------------------
model_edges = Table(
    "model_edges", metadata,
    Column("edge_id", _BIGID, primary_key=True, autoincrement=True),
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("kind", String, nullable=False),                     # call|global_access|type_use|macro_use|override
    Column("src_key", String, nullable=False),
    Column("dst_key", String, nullable=False),
    Column("mode", String),                                     # read|write (global_access only)
    Index("ix_edges_reverse", "version_id", "kind", "dst_key"),   # who depends on X (impact)
    Index("ix_edges_forward", "version_id", "kind", "src_key"),
)

# ---------------------------------------------------------------------------
# G7 — Change detection / reuse  (entity_hashes folded into entity_versions.source_hash)
# ---------------------------------------------------------------------------
reuse_index = Table(
    "reuse_index", metadata,
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("fingerprint", String, nullable=False),
    Column("version_id", String),
    Column("entity_key", String),
    UniqueConstraint("project_id", "fingerprint", name="pk_reuse_index"),
)

tu_includes = Table(
    "tu_includes", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("tu_path", String, nullable=False),
    Column("headers", _JSONB),                                  # narrowed-parse include closure
    UniqueConstraint("version_id", "tu_path", name="pk_tu_includes"),
)

# ---------------------------------------------------------------------------
# Project inputs (were CSV files)
# ---------------------------------------------------------------------------
data_dictionaries = Table(
    "data_dictionaries", metadata,
    Column("id", String, primary_key=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("name", String),
    _ts("uploaded_at"),
)

data_dictionary_entries = Table(
    "data_dictionary_entries", metadata,
    Column("id", _BIGID, primary_key=True, autoincrement=True),
    Column("data_dictionary_id", String, ForeignKey("data_dictionaries.id", ondelete="CASCADE"), nullable=False),
    Column("payload", _JSONB, nullable=False),                  # one CSV row; shape refined at ingest
)

macro_definitions = Table(
    "macro_definitions", metadata,
    Column("id", _BIGID, primary_key=True, autoincrement=True),
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("layer", String),                                    # per-layer macros (open V1 requirement)
    Column("name", String, nullable=False),
    Column("value", Text),
)

# ---------------------------------------------------------------------------
# View outputs (were Phase-3 JSON/mmd; consumed by Phase 4 + the API)
# ---------------------------------------------------------------------------
view_interface_tables = Table(
    "view_interface_tables", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("scope", String, nullable=False),
    Column("payload", _JSONB, nullable=False),
    UniqueConstraint("version_id", "scope", name="pk_view_interface_tables"),
)

view_behaviour_rows = Table(
    "view_behaviour_rows", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("scope", String, nullable=False),
    Column("payload", _JSONB, nullable=False),
    UniqueConstraint("version_id", "scope", name="pk_view_behaviour_rows"),
)

model_unit_diagrams = Table(
    "model_unit_diagrams", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("unit_key", String, nullable=False),
    Column("mermaid_hash", String, ForeignKey("content_blobs.content_hash")),
    UniqueConstraint("version_id", "unit_key", name="pk_model_unit_diagrams"),
)

model_flowcharts = Table(
    "model_flowcharts", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("entity_id", BigInteger, ForeignKey("entities.entity_id"), nullable=False),
    Column("mermaid_hash", String, ForeignKey("content_blobs.content_hash")),
    Column("error", Text),
    UniqueConstraint("version_id", "entity_id", name="pk_model_flowcharts"),
)


# Tables whose rows belong to one version — CASCADE-deleted with it. Used by the
knowledge_base = Table(
    "knowledge_base", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"),
           primary_key=True),
    Column("payload", _JSONB, nullable=False),
)
"""The project knowledge object Phase 2 builds and Phase 3's flowchart engine consumes
(doc 10, step 6). Previously `model/knowledge_base.json`.

One row per version, whole-object: it is loaded in full by `pkb/builder.py` and never queried
per field, so normalising it would buy nothing. D-12 intends to REPLACE it with a per-target
context service (doc 09, C7); until then it needs a home that is not a local file, because a
cross-machine `--from-phase 3` currently loses it and the flowchart engine silently degrades to
less context for its node labels."""


incremental_plans = Table(
    "incremental_plans", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"),
           primary_key=True),
    Column("payload", _JSONB, nullable=False),
)
"""What an incremental run tells Phase 2 and Phase 3 to regenerate (doc 10, step 6).
Previously `model/incremental_plan.json`.

Carries impactFids / impactedGlobals / impactedFiles / flowchartFids / flowchartFiles /
crossVersionFlowcharts / baselineVersionDir. Whole-object again — every reader loads all of it.

This is also what makes the flowchart engine able to restrict itself by version id (D10-5): the
changed-function list is far too long for a command line, so the engine reads the plan."""


llm_description_cache = Table(
    "llm_description_cache", metadata,
    Column("project_id", String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
    Column("namespace", String, nullable=False),          # llm_descriptions | aux_descriptions
    Column("cache_version", Integer, nullable=False),     # llm.cacheVersion — bump to invalidate
    Column("entity_id", String, nullable=False),
    Column("content_hash", String, nullable=False),       # entity source + sorted callee hashes
    Column("value", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    UniqueConstraint("project_id", "namespace", "cache_version", "entity_id", "content_hash",
                     name="pk_llm_description_cache"),
    Index("ix_llm_description_cache_scope", "project_id", "namespace", "cache_version"),
)
"""LLM descriptions keyed by content, replacing `.flowchart_cache/{llm,aux}_descriptions/*.json`
(doc 04 §13, doc 10 step 10).

Named `…_cache` deliberately: this is the one kind of data here that may be **discarded** without
loss — every row can be recomputed by calling the LLM again — so it is the natural candidate to
move to a cache server later, and the name marks it.

A disk cache is close to worthless on the target deployment: a container filesystem is ephemeral,
so it dies on restart, and a cache on node A is invisible to node B, giving N nodes a ~1/N hit
rate. That is not a small loss. The gateway admits roughly one call every three seconds, so a
cold cache on a 20k-function project is measured in hours, and it is the *full* generation path
that depends on this — the reuse index carries descriptions forward only on the incremental path.

**Scoped per project, not per version** (§13.3), which is the whole point of a cache: a version
that re-describes identical code should hit rows written by an earlier one. `cache_version` is in
the key rather than a filter so that bumping `llm.cacheVersion` invalidates by construction and
leaves the old rows harmlessly unreferenced.

Reads are **batched into one query per namespace** — never one statement per entity. That is not
a micro-optimisation: per-entity lookups on a 20k-function project mean 20k round trips (doc 09
B5a), which costs more than the LLM calls it is trying to avoid."""


parse_snapshots = Table(
    "parse_snapshots", metadata,
    Column("version_id", String, ForeignKey("versions.id", ondelete="CASCADE"), nullable=False),
    Column("name", String, nullable=False),                     # "functions.json", "hashes.json", …
    Column("payload", _JSONB, nullable=False),
    UniqueConstraint("version_id", "name", name="pk_parse_snapshots"),
    Index("ix_parse_snapshots_version", "version_id"),
)
"""The post-Phase-1 model — the blank skeleton, before Phase 2 fills in LLM descriptions
(doc 09, C2). Previously `versions/<ver>/parse/` on local disk, which meant a narrowed parse
only worked on the machine that produced the baseline.

Kept SEPARATE from the enriched model rather than tagging `entity_versions` with a phase, for
one decisive reason: this snapshot is never queried per entity. `parse_merge` loads the whole
thing and merges dicts, so normalising it would add a phase column to the busiest table (and
to its uniqueness constraint) for no query benefit and real regression risk.

Storing it verbatim also preserves the property that matters: a field added to the model later
cannot go missing from the skeleton, which is exactly the failure mode of reconstructing it by
stripping LLM fields.

One row per file rather than one blob per version: `functions.json` alone reaches tens of MB on
a large project, and a reader that only wants `hashes.json` should not pull it."""


# retention/delete path and asserted in tests so a new per-version table can't be
# added without a delete story.
PER_VERSION_TABLES = frozenset({
    "entity_versions", "model_units", "model_components", "model_summaries",
    "model_edges", "tu_includes", "view_interface_tables", "view_behaviour_rows",
    "model_unit_diagrams", "model_flowcharts", "documents", "parse_snapshots", "knowledge_base", "incremental_plans",
})
