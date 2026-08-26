"""Where the e2e pipeline runs and where it puts its output.

poc-4 drove the pipeline with

    python engine/run.py SampleCppProject --clean --selected-group "My Sample"

and read the result from PROJECT_ROOT/output/My-Sample/. Neither half of that works
in database mode, for two reasons that are both deliberate product decisions rather
than test drift:

  * run.py now needs to know WHICH version row it is writing into, so it requires
    --version-id / --project-id. Without them Phase 1 stops with "no model repository
    is installed for this run". The supported way to supply them is the analyzer CLI,
    which owns onboarding and version creation:

        analyzer.py onboard  --project-id ... --source <repo> --version-id ...
        analyzer.py generate --project-id ... --version-id ... --scope "group:My Sample"

  * documents are produced per COMPONENT, not per group. `--component-per-docx` is
    added for every scope except a single-component one (incremental/generate.py:220),
    so "My Sample" yields Lib / Sample-Core / Util rather than one My-Sample.

The source tree is copied to a scratch git repo and committed: a version is identified
by a commit, so the sample needs one of its own rather than borrowing the analyzer
repo's HEAD.

Everything here is computed at import time from fixed ids, so test modules can build
their paths at module scope exactly as they did before.
"""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAMPLE_PROJECT = os.path.join(PROJECT_ROOT, "SampleCppProject")

# Fixed so every path below is knowable before the pipeline has run.
E2E_PID = "e2e-sample"
E2E_VID = "e2ev1"
GROUP = "My Sample"

# The components "My Sample" covers, in config.defaults.json. Documents, interface
# tables and unit diagrams are produced once per entry.
COMPONENTS = ("Lib", "Sample-Core", "Util")

VERSION_DIR = os.path.join(PROJECT_ROOT, "workspaces", E2E_PID, "versions", E2E_VID)
OUTPUT_DIR = os.path.join(VERSION_DIR, "output")
DOCUMENTS_DIR = os.path.join(VERSION_DIR, "documents")

# Phase 1 and 2 write the model to the database, not to disk. conftest materialises it
# here after the run (model_store.dump_model_to_dir) so the model-shape tests can read
# the same JSON they always read -- the model is still sourced from the database, the
# files are a hand-off.
MODEL_DIR = os.path.join(VERSION_DIR, "model_dump")


def output_for(component: str) -> str:
    """That component's output directory."""
    return os.path.join(OUTPUT_DIR, component)


def docx_for(component: str) -> str:
    """That component's design document."""
    return os.path.join(OUTPUT_DIR, component, f"software_detailed_design_{component}.docx")


def existing_docx() -> list:
    """Every design document the run actually produced, in COMPONENTS order."""
    return [p for p in (docx_for(c) for c in COMPONENTS) if os.path.isfile(p)]
