# UT Export — Field Readiness

How ready each field of the two UT-automation JSON files is.

**Scope:** unit tests only, generated from SWE.4 (integration tests will come from SWE.2) ·
**Rules:** [UT_EXPORT_SPEC](UT_EXPORT_SPEC.md) · **Templates:** [ut_templates](ut_templates/README.md)

## The Two Files

Both are written to `output/ut/`.

- **Hierarchy file** (`hierarchy.json`) — one per project: layers, sections and test environments,
  with macros and include paths
- **Test-case file** (`<env>.json`) — one per unit: its test cases, with inputs, stubs and expected results

## Summary

- **Generated:** both files, plus our own `ut_export.json` per group
- **Validated:** `tools/check_ut_json.py` reports 0 errors
- **Sample project:** every test case solved — inputs and expected values
- **Names:** layer and core names come from the project config (Sample: `Layer1`, `Core1`)
- **Open items:** in the last column of each table

## Legend

- **Status:** ✅ Done · 🟡 Partial — more work needed · 📥 Input — supplied from outside ·
  ❓ Blocked — needs an answer · ➖ Out of scope
- **Based on:** Agreed — decided with the team · Assumed — our choice, the sample is silent ·
  Sample — follows the sample · Config — set in the project config (`views.utExport`) ·
  Code — computed from the source · Checked — confirmed in our code
- **Open question:** ❓ needs an answer · 🔍 a real file will settle it

## Hierarchy File — `hierarchy.json`

Row names: `layer ›`, `section ›` and `environment ›` mean a field inside `LayerMapping.<layer>`,
`….Sections.<section>` and `….TestEnvironments.<env>`.

| Field | Status | Current | Based on | Open question |
|---|---|---|---|---|
| File | ✅ Done | One per project, in `output/ut/`; rebuilt on every run | Agreed | — |
| `Macros.<core>Macros` | ✅ Done | The layer's compiler defines, as `NAME=value` | Assumed | — |
| layer | ✅ Done | Each configured layer | Config | — |
| layer › `searchdirectories` | ✅ Done | The layer's include folders, relative to the project | Assumed | — |
| layer › `Librarydirectories` | 📥 Input | `libraryDirectories.<layer>`; empty by default | Config | — |
| section | ✅ Done | One per unit | Agreed | 🔍 Is a section a unit, a component or a group? |
| section › `SectionID` | ✅ Done | Unit key, e.g. `Layer1.Sample-Core\|Core` | Assumed | ❓ What format? Sample: `ABC1` |
| section › `SectionName` | ✅ Done | Unit name | Assumed | — |
| environment | ✅ Done | One per unit | Agreed | — |
| environment › `EnvironmentId` | ✅ Done | Same as `EnvironmentName` | Assumed | ❓ What format? Sample: `PQR1` |
| environment › `EnvironmentName` | ✅ Done | `<LAYER>_<COMPONENT>_<UNIT>_TS` | Assumed | 🔍 The sample has `<SECTION>` where we put the component |
| environment › `Filename`, `FilePath` | ✅ Done | The unit's source file, relative to the project | Assumed | — |
| environment › `IsHeader` | ✅ Done | `true` only when the unit is just a header | Assumed | — |
| environment › `CoreType` | ✅ Done | The layer's core | Agreed | ❓ Can one layer mix cores? Sample: `SED` + `FCore` |
| environment › `Probepoint[]`, `usercode[]` | 📥 Input | `environments.<env>.hierarchy`; empty by default | Config | — |
| environment › `Testcase` | ✅ Done | `<env>.json`, in the same folder | Assumed | — |

## Test-Case File — `<env>.json`

| Field | Status | Current | Based on | Open question |
|---|---|---|---|---|
| File | ✅ Done | One per unit, in `output/ut/` | Agreed | — |
| Dynamic-behaviour cases | ✅ Done | In the file of the unit where the flow starts | Assumed | — |
| `format_version` | ✅ Done | `"1.0"` | Sample | ❓ `1.0` or `v0.1` (older guide)? |
| `environment.name` | ✅ Done | The environment name | Assumed | 🔍 Same as `EnvironmentName` in the hierarchy? |
| `environment.flags`, `probepoint[]`, `usercode[]` | 📥 Input | `environment`, or per environment `environments.<env>.testcase` | Config | — |
| `cases[].id` | ✅ Done | Ours, e.g. `TC_IF_LAYER1_CORE_06_01` | Assumed | ❓ What format? Sample: `<TEST-CASE-ID-001>` |
| `cases[].name` | ✅ Done | `<function> returns <value> at step <n>` | Assumed | — |
| `cases[].level` | ✅ Done | `UT` | Agreed | — |
| `cases[].trace` | 📥 Input | Empty until requirement IDs exist | — | — |
| `cases[].review.author`, `reviewer` | 📥 Input | `review` | Config | — |
| `cases[].target.unit`, `function` | ✅ Done | Class method: class + method · C function: unit + function | Assumed | — |
| `cases[].target.class`, `constructor`, `destructor` | 🟡 Partial | Supported, but the parser does not read constructors / destructors yet | Checked | — |
| `cases[].preconditions.globals[]` | ✅ Done | Globals the path reads, with the value to set | Code | — |
| Class members in `preconditions.globals[]` | 🟡 Partial | Not available: the parser does not record `this->member` reads | Checked | — |
| `cases[].stubs[].mode` | ✅ Done | `prototype` if the stub writes data back, else `faked` | Agreed | ❓ Is this the right rule? |
| `cases[].stubs[].unit`, `function` | ✅ Done | `faked`: class or unit + name · `prototype`: `uut_prototype_stubs` + full name | Sample | — |
| `cases[].stubs[].returns.value` | ✅ Done | The chosen return value; `""` when the stub returns nothing | Assumed | ❓ How is a void stub written? Sample has none |
| `cases[].stubs[].prototype_values` | ✅ Done | One entry per field the stub writes back: `<param>.<field>` | Sample | — |
| `cases[].inputs[].param`, `value` | ✅ Done | A solved value for each parameter; `0` when any value works | Code | — |
| `cases[].inputs[]` — output parameter | 🟡 Partial | `null`, with a note | Assumed | ❓ How is an output buffer passed? |
| `cases[].inputs[]` — pointer that must be valid | 🟡 Partial | `null`, with a note | Assumed | ❓ How is a real object passed? |
| `cases[].inputs[].value` — struct | ✅ Done | `{type, fields}` with the solved fields | Sample | — |
| `cases[].inputs[].value` — array | 🟡 Partial | Not solved yet | — | — |
| `cases[].inputs[].escape_hatch` | ❓ Blocked | Not generated | — | ❓ When is it allowed? Where do `IN-XX` IDs come from? |
| `cases[].expected.return.value` | ✅ Done | Computed for the path; `null` if void or not computable | Code | — |
| `cases[].expected.globals[]` | ✅ Done | Globals the path writes, when the value is computable | Code | — |
| `cases[].expected.class_members[]` | 🟡 Partial | Empty: the parser does not record member writes | Checked | — |
| `cases[].expected.stub_params[]` | ✅ Done | Each stub called on the path, with its known arguments | Code | — |
| `cases[].expected.*.derived_from` | 📥 Input | Empty until requirement IDs exist | — | — |
| `cases[].steps[]` | ➖ Out of scope | Integration tests only | — | — |
