"""Unit tests for src/incremental/report.py — end-of-run report (M3.4)."""
import os
import sys
import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from incremental.report import build_report


def _incremental_stats():
    return {
        "versionId": "v2", "decision": "incremental", "status": "complete",
        "projectId": "samplecpp", "branch": "main", "commit": "3433fd6d6911",
        "scope": "group:Support", "baselineVersionId": "v1", "baselineCommit": "08d2f565cd03",
        "changedFiles": 3, "dataDictId": "dd-001",
        "llmModel": "openai/gpt-oss-120b", "elapsedSeconds": 123.4,
        "classification": {"changed": {"function": 3}, "new": {}, "deleted": {},
                           "unchanged": {"function": 110, "global": 12, "type": 14, "macro": 9}},
        "functions": {"total": 113, "regenerated": 9, "reused": 104},
        "globals": {"total": 12, "regenerated": 3, "reused": 9},
        "files": {"total": 18, "regenerated": 5, "carried": 13},
        "documents": ["software_detailed_design_Support.docx"], "warnings": [],
    }


class TestBuildReport:
    def test_incremental_has_key_sections_and_numbers(self):
        text = "\n".join(build_report(_incremental_stats()))
        assert "GENERATION REPORT" in text and "incremental" in text
        assert "Baseline" in text and "v1 @ 08d2f565cd" in text and "3 changed file" in text
        assert "regenerated 9" in text and "reused 104 (92%)" in text          # functions
        assert "regenerated 3" in text and "reused 9 (75%)" in text            # globals
        assert "carried 13 (72%)" in text                                       # flowcharts
        assert "software_detailed_design_Support.docx" in text
        assert "123.4s" in text

    def test_classification_rendered(self):
        text = "\n".join(build_report(_incremental_stats()))
        assert "changed   : 3" in text
        assert "unchanged : 145" in text  # 110+12+14+9

    def test_warnings_listed(self):
        s = _incremental_stats(); s["warnings"] = ["base v9 is not an ancestor - close to full"]
        text = "\n".join(build_report(s))
        assert "Warnings:" in text and "not an ancestor" in text

    def test_full_report_notes_no_baseline(self):
        s = _incremental_stats()
        s.update(decision="full", classification=None,
                 functions={"total": 113, "regenerated": 113, "reused": 0})
        text = "\n".join(build_report(s))
        assert "full" in text and "full generation" in text
        assert "reused 0 (0%)" in text
        assert "CHANGE CLASSIFICATION" not in text   # only shown for incremental

    def test_pct_safe_on_zero_total(self):
        s = _incremental_stats(); s["globals"] = {"total": 0, "regenerated": 0, "reused": 0}
        text = "\n".join(build_report(s))   # must not raise ZeroDivisionError
        assert "reused 0 (0%)" in text
