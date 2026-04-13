# Tasks

## Immediate
- [x] Add `.gitignore` (`.claude/`, `.flowchart_cache/`, `model/`, `output/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`)
- [ ] Commit remaining changes (exclude `.claude/`, `.flowchart_cache/`)
- [ ] Push to `origin/feature/test-framework`

---

## Test Coverage

### DOCX Sections

| Section | Integration | E2E | Snapshot | Status |
|---|---|---|---|---|
| interfaceTables | ✅ thorough | ✅ good | ✅ | Good |
| unitDiagrams | ✅ good | ✅ PNG placed | ❌ | Good, no snapshot |
| behaviourDiagram | ✅ moderate | ✅ moderate | ❌ | Moderate |
| flowcharts | ✅ moderate | ⚠️ thin | ❌ | Moderate |
| moduleStaticDiagram (inline) | ❌ | ⚠️ heading only, no PNG check | ❌ | Bare minimum |
| Component/Unit table (inline) | ❌ | ❌ | ❌ | Not tested |
| unit header table (inline) | ❌ | ❌ | ❌ | Not tested |

> `moduleStaticDiagram`, Component/Unit table, and unit header table are built inline in
> `docx_exporter.py` — not registered views.

### Pipeline Phases

| Phase | Status | Gap |
|---|---|---|
| Phase 1 — parser.py | Indirect only | No unit tests |
| Phase 2 — model_deriver.py | Partial (behaviour names) | Direction, interfaceId, transitive globals untested |
| Phase 3 — run_views.py | Indirect only | All-groups mode never tested |
| Phase 4 — docx_exporter.py | ✅ good | — |

### Supporting Modules

| Module | Status | Gap |
|---|---|---|
| llm_client.py | ✅ full | — |
| utils.py | ❌ none | Comment stripping, trailing commas, config merge |
| run.py (CLI) | ❌ none | `_parse_args`, group resolution, `--use-model` mode |

---

## Bugs
- [x] Typo in `tests/conftest.py:97` — `--no-llm-summerize` → `--no-llm-summarize`

---

## Test Gaps to Fill

### High priority
- [x] `src/utils.py` unit tests — comment stripping, trailing commas, config merge
- [x] `run.py` CLI unit tests — `_resolve_group_name`, case-insensitive group resolution
- [ ] Snapshot for `unit_diagrams/*.mmd`
- [x] E2E: check moduleStaticDiagram PNG or Mermaid text present in Static Design section
- [x] E2E: Component/Unit table and unit header table present and correct

### Medium priority
- [ ] `src/model_deriver.py` unit tests — direction, interfaceId, transitive globals
- [ ] Validate `model/units.json`, `modules.json`, `globalVariables.json` directly

### Low priority
- [ ] Test `--use-model` / `--skip-model` mode
- [ ] Test all-groups mode (no `--selected-group`)
- [ ] Edge-case scenario: all-private project, no globals, no external callers
