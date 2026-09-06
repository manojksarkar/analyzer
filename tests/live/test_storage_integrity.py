"""Is what the database holds internally consistent?

`content_blobs` is content-addressed: the hash IS the identity. If a payload does not hash
to its own content_hash then the reuse index can never match that entity again, and two
different payloads can collide onto one row.
"""
import json

import pytest

pytestmark = pytest.mark.live


def _has_nul(value):
    if isinstance(value, str):
        return "\x00" in value
    if isinstance(value, dict):
        return any(_has_nul(k) or _has_nul(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_has_nul(v) for v in value)
    return False


def _blobs(db, vid):
    """Every blob this version's entities point at, as (hash, payload)."""
    rows = db.rows(
        "select b.content_hash, b.payload from content_blobs b "
        "where b.content_hash in ("
        "  select distinct content_hash from entity_versions "
        "  where version_id = :v and content_hash is not null)", v=vid)
    out = []
    for h, payload in rows:
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        out.append((h, payload))
    return out


class TestContentAddressing:
    def test_every_blob_hashes_to_its_own_content_hash(self, db, vid):
        from core.model_store import _content_hash
        blobs = _blobs(db, vid)
        if not blobs:
            pytest.skip("version %s references no content blobs" % vid)
        bad = [h for h, payload in blobs if _content_hash(payload) != h]
        assert not bad, (
            "%s: %d of %d blob(s) do not hash to their content_hash.\n"
            "content_blobs is content-addressed -- the hash is the identity. A mismatch "
            "means the payload was altered after hashing (a scrub applied on the way in, "
            "for instance), so the reuse index will never match this entity again.\n      %s"
            % (vid, len(bad), len(blobs), "\n      ".join(h[:16] for h in bad[:8])))

    def test_every_payload_pointer_resolves(self, db, vid):
        dangling = [r[0] for r in db.rows(
            "select distinct ev.content_hash from entity_versions ev "
            "left join content_blobs b on b.content_hash = ev.content_hash "
            "where ev.version_id = :v and ev.content_hash is not null "
            "and b.content_hash is null", v=vid)]
        assert not dangling, (
            "%s: %d payload pointer(s) have no blob. The entity reads back with no "
            "parameters and no description.\n      %s"
            % (vid, len(dangling), "\n      ".join(h[:16] for h in dangling[:8])))


class TestNoUnstorableCharacters:
    def test_no_blob_contains_a_nul(self, db, vid):
        blobs = _blobs(db, vid)
        if not blobs:
            pytest.skip("version %s references no content blobs" % vid)
        bad = [h for h, payload in blobs if _has_nul(payload)]
        assert not bad, (
            "%s: %d blob(s) contain a NUL character.\n"
            "PostgreSQL cannot represent one in text or jsonb, so if one is stored the "
            "scrub in db_util was bypassed -- and the next write of the same content will "
            "fail the whole phase.\n      %s"
            % (vid, len(bad), "\n      ".join(h[:16] for h in bad[:8])))


class TestEntityIdentity:
    def test_no_entity_key_is_duplicated_within_a_version(self, db, vid):
        dupes = db.rows(
            "select e.entity_key, count(*) c from entity_versions v "
            "join entities e on e.entity_id = v.entity_id "
            "where v.version_id = :v group by e.entity_key having count(*) > 1", v=vid)
        assert not dupes, (
            "%s: %d entity key(s) appear more than once in one version.\n"
            "entity_versions is unique on (version_id, entity_id), so a repeated KEY means "
            "two entity rows share a key -- the same function stored twice under two ids, "
            "and readers get whichever one the join returns.\n      %s"
            % (vid, len(dupes), "\n      ".join("%s x%d" % (r[0], r[1]) for r in dupes[:8])))

    def test_every_entity_belongs_to_this_project(self, db, project_id, vid):
        leaked = db.scalar(
            "select count(*) from entity_versions v "
            "join entities e on e.entity_id = v.entity_id "
            "where v.version_id = :v and e.project_id <> :p", v=vid, p=project_id)
        assert not leaked, (
            "%s: %d row(s) point at an entity owned by ANOTHER project. entities is keyed "
            "(project_id, entity_key), so this means a version is reading another "
            "project's model." % (vid, leaked))
