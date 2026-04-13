# Tasks

## Immediate
- [x] Add `.gitignore`
- [x] Commit all changes (5 short commits)
- [ ] Push to `origin/feature/test-framework`

---

## Test Coverage

### DOCX Sections

| Section | Integration | E2E | Snapshot | Status |
|---|---|---|---|---|
| interfaceTables | ✅ thorough | ✅ good | ✅ | Good |
| unitDiagrams | ✅ good | ✅ PNG placed | ✅ | Good |
| behaviourDiagram | ✅ moderate | ✅ moderate | ❌ | Moderate |
| flowcharts | ✅ moderate | ⚠️ thin | ❌ | Moderate |
| moduleStaticDiagram (inline) | ❌ | ✅ PNG/Mermaid check added | ❌ | Moderate |
| Component/Unit table (inline) | ❌ | ✅ headers + module names | ❌ | Moderate |
| unit header table (inline) | ❌ | ✅ header row check | ❌ | Moderate |

### Pipeline Phases

| Phase | Status | Gap |
|---|---|---|
| Phase 1 — parser.py | Indirect only | No unit tests |
| Phase 2 — model_deriver.py | ✅ good | — |
| Phase 3 — run_views.py | Indirect only | All-groups mode never tested |
| Phase 4 — docx_exporter.py | ✅ good | — |

### Supporting Modules

| Module | Status | Gap |
|---|---|---|
| llm_client.py | ✅ full | — |
| utils.py | ✅ full | — |
| run.py (CLI) | ✅ `_resolve_group_name` | `--use-model` mode, from-phase logic |

---

## Bugs
- [x] Typo in `tests/conftest.py:97` — `--no-llm-summerize` → `--no-llm-summarize`

---

## Test Gaps to Fill

### High priority
- [x] `src/utils.py` unit tests — comment stripping, trailing commas, config merge
- [x] `run.py` CLI unit tests — `_resolve_group_name`, case-insensitive group resolution
- [x] Snapshot for `unit_diagrams/*.mmd`
- [x] E2E: check moduleStaticDiagram PNG or Mermaid text present in Static Design section
- [x] E2E: Component/Unit table and unit header table present and correct

### Medium priority
- [x] `src/model_deriver.py` unit tests — direction, interfaceId, transitive globals
- [x] Validate `model/units.json`, `modules.json`, `globalVariables.json` directly

### Low priority
- [ ] Test `--use-model` / `--skip-model` mode
- [ ] Test all-groups mode (no `--selected-group`)
- [ ] Edge-case scenario: all-private project, no globals, no external callers
