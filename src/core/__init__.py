"""Cross-cutting infrastructure used by both the analyzer and the flowchart engine.

Currently provides:
  - logging_setup : configures stdlib logging with stderr + rotating file handler
  - progress      : ProgressReporter for live `[idx/total]` progress on TTYs

Both modules are deliberately small and have no third-party dependencies.
"""

from .logging_setup import configure_logging, get_logger, set_level
from .progress import ProgressReporter
from .paths import ProjectPaths, paths, set_project_root
from .config import (
    app_config,
    llm_config,
    views_config,
    exporter_config,
    clang_config,
    modules_groups,
)
from .model_io import (
    METADATA,
    FUNCTIONS,
    GLOBALS,
    UNITS,
    MODULES,
    DATA_DICTIONARY,
    KNOWLEDGE_BASE,
    SUMMARIES,
    ALL_MODEL_NAMES,
    ModelFileMissing,
    model_file_path,
    model_files_present,
    read_model_file,
    write_model_file,
    load_model,
    ensure_model_dir,
)
from .orchestration import Phase, PhaseRunner
from .group_planner import (
    RunPlan,
    plan_runs,
    PHASE_PARSE,
    PHASE_DERIVE,
    PHASE_VIEWS,
    PHASE_EXPORT,
)

__all__ = [
    "configure_logging",
    "get_logger",
    "set_level",
    "ProgressReporter",
    "ProjectPaths",
    "paths",
    "set_project_root",
    "app_config",
    "llm_config",
    "views_config",
    "exporter_config",
    "clang_config",
    "modules_groups",
    "METADATA",
    "FUNCTIONS",
    "GLOBALS",
    "UNITS",
    "MODULES",
    "DATA_DICTIONARY",
    "KNOWLEDGE_BASE",
    "SUMMARIES",
    "ALL_MODEL_NAMES",
    "ModelFileMissing",
    "model_file_path",
    "model_files_present",
    "read_model_file",
    "write_model_file",
    "load_model",
    "ensure_model_dir",
]
