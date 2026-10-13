"""
Output writer.

Writes one JSON file per source file into --out-dir.
Each JSON file contains an array of flowchart results.

Output filename: <source_file_basename>.json
  e.g. src/qos/qos_event_manager.cpp → <out-dir>/qos_event_manager.json

Output JSON schema (per file):
[
  {
    "functionKey": "src|qos_event_manager|pos::QosEventManager::_RateLimit|...",
    "name": "pos::QosEventManager::_RateLimit",
    "flowchart": "flowchart TD\n    ...",
    "cfg": {"entry": "n0", "exits": ["n7"],
            "nodes": [{"id", "type", "label", "rawCode", "line", "endLine"}],
            "edges": [{"source", "target", "label"}]}
  },
  ...
]

"flowchart" is the rendering; "cfg" is the graph it was rendered from, kept for
consumers that need the structure (SWE.4 transcribes it into Test Steps). It is
omitted when the CFG could not be built.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from models import FileResult, FlowchartResult

logger = logging.getLogger(__name__)


class OutputWriter:
    """Writes per-source-file JSON output to out_dir."""

    def __init__(self, out_dir: str, chart_names: Optional[Dict[str, str]] = None) -> None:
        self._out_dir = Path(out_dir)
        self._out_dir.mkdir(parents=True, exist_ok=True)
        # {function key: the chart's name in its unit file}. A chart is keyed by name inside the
        # file, and by it on disk (<unit>_<name>.png / .svg): overloads share a qualified name,
        # so each needs one of its own (core.function_names.chart_names).
        self._chart_names = dict(chart_names or {})

    def write_file_result(self, file_result: FileResult) -> Path:
        """
        Serialize a FileResult and write it to out_dir.
        Returns the path of the written file.
        """
        source_path = Path(file_result.source_file)
        # Use only the stem (filename without extension) + .json
        out_name = source_path.stem + ".json"
        out_path = self._out_dir / out_name

        payload = _serialize_file_result(file_result, self._chart_names)

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        logger.info("Written %d flowchart(s) → %s",
                    len(file_result.flowcharts), out_path)
        return out_path

    def write_all(self, file_results: List[FileResult]) -> List[Path]:
        """Write all file results and return paths."""
        written = []
        for fr in file_results:
            if fr.flowcharts:
                written.append(self.write_file_result(fr))
        return written

    def write_summary(self, file_results: List[FileResult],
                      total_functions: int,
                      total_errors: int) -> Path:
        """Write a summary JSON listing all output files and statistics."""
        summary = {
            "totalFunctions": total_functions,
            "totalErrors": total_errors,
            "files": [
                {
                    "sourceFile": fr.source_file,
                    "flowchartsGenerated": sum(
                        1 for fc in fr.flowcharts if not fc.error
                    ),
                    "errors": sum(
                        1 for fc in fr.flowcharts if fc.error
                    ),
                }
                for fr in file_results
            ],
        }
        out_path = self._out_dir / "_summary.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        logger.info("Summary written → %s", out_path)
        return out_path


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _serialize_file_result(file_result: FileResult,
                           chart_names: Optional[Dict[str, str]] = None) -> List[Dict]:
    """Convert FileResult → JSON-serializable list."""
    result = []
    for fc in file_result.flowcharts:
        entry: Dict = {
            "functionKey": fc.function_key,
            "name": (chart_names or {}).get(fc.function_key) or fc.qualified_name,
            "flowchart": fc.mermaid_script,
        }
        if fc.cfg:
            entry["cfg"] = fc.cfg
        if fc.error:
            entry["error"] = fc.error
        result.append(entry)
    return result
