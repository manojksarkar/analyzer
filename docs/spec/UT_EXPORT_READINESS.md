# UT Export — readiness

Each field of the two UT-automation JSON files vs what ArtiFex emits today.
Rules → [UT_EXPORT_SPEC](UT_EXPORT_SPEC.md) · templates → [ut_templates](ut_templates/README.md).
**Scope:** UT only, from SWE.4; IT comes from SWE.2.

✅ generated · 🟡 data available, build work only · 📥 input, supplied from outside ·
🔍 doubt, our assumption — verify by looking · ❓ open question — needs an answer · ➖ out of scope

**Today**
- Test-case file: `views/ut_export.py`, input values `null`. Hierarchy file: not built.
- Key names: several are still ours — `python tools/check_ut_json.py <file>` lists them (28 on the Sample).
- Project names come from config (user input); the Sample uses `Layer1`/`Layer2`, `Core1`/`Core2`.
- "Path solving" rows wait on one thing: branch conditions exist only as English text ([REQ-UE-04](UT_EXPORT_SPEC.md)).

## Hierarchy file

layer = `LayerMapping.<layer>` · section = `….Sections.<section>` · environment = `….TestEnvironments.<env>`

| Field | Status | Note |
|---|---|---|
| `Macros.<core>Macros` | 🟡 | config `cores.<core>.macros` |
| layer | 🟡 | config `layers` |
| layer › `searchdirectories` | 🟡 | layer + include paths |
| layer › `Librarydirectories` | 📥 | user; no config key yet |
| section | 🟡 🔍 D1 | Assumed a component, not a group — a real file settles it (one folder per section = component) |
| section › `SectionID` | ❓ Q2 | Format? Sample `ABC1` |
| section › `SectionName` | 🟡 | |
| environment | 🟡 | one per unit |
| environment › `EnvironmentId` | ❓ Q3 | Format? Sample `PQR1`, `FIL1` |
| environment › `EnvironmentName` | 🟡 | `<LAYER>_<SECTION>_<UNIT>_TS` |
| environment › `Filename`, `FilePath`, `IsHeader` | 🟡 | |
| environment › `CoreType` | 🟡 ❓ Q6 | The layer's core (config). Can a layer mix cores? Sample has `SED` + `FCore` in one layer; our config allows one |
| environment › `Probepoint[]`, `usercode[]` | 📥 | user, per environment; no config key yet |
| environment › `Testcase` | 🟡 | path to this unit's test-case file |

## Test-case file

| Field | Status | Note |
|---|---|---|
| the file itself | 🟡 | One per unit (test environment). Today one per group — needs a split per unit |
| `format_version` | ✅ | |
| `environment.name` | 🟡 🔍 D4 | Assumed equal to its environment's `EnvironmentName` — check a real pair of files |
| `environment.flags`, `probepoint[]`, `usercode[]` | 📥 | config `views.utExport.environment` |
| `cases[].id` | ✅ ❓ Q1 | Format? Sample `<TEST-CASE-ID-001>`; ours `TC_IF_LAYER1_CORE_06_01` |
| `cases[].name` | ✅ | |
| `cases[].level` | ✅ | `"IT"` ➖ |
| `cases[].trace` | 📥 | requirement ID (Polarion / SWE.1); empty until then |
| `cases[].review.author`, `reviewer` | 📥 | config `views.utExport.review` |
| `cases[].target.function`, `class` | ✅ | ours: `FunctionName`, `ClassName` |
| `cases[].target.unit` | 🟡 | |
| `cases[].target.constructor`, `destructor` | 🟡 🔍 D3 | Assumed constructors / destructors get SWE.4 specs — check `views/test_specs.py` |
| `cases[].preconditions.globals[].name` | ✅ | |
| `cases[].preconditions.globals[].unit` | 🟡 | |
| `cases[].preconditions.globals[].value` | 🟡 | path solving |
| class members in `preconditions.globals[]` | 🟡 🔍 D2 | Assumed the model records non-static member reads/writes — check the parser |
| `cases[].stubs[].function` | ✅ | |
| `cases[].stubs[].unit` | 🟡 | |
| `cases[].stubs[].mode` | ❓ Q4 | When `faked`, when `prototype`? Our reading: both are stubs; `prototype` is built from a declaration only and can write back (`prototype_values`) |
| `cases[].stubs[].returns.value` | 🟡 | path solving |
| `cases[].stubs[].prototype_values` | 🟡 | |
| `cases[].inputs[].param` | ✅ | ours: `name` |
| `cases[].inputs[].value` | 🟡 | path solving; `null` today |
| `cases[].inputs[].escape_hatch` | ❓ Q5 | Which inputs may use it? Where do `IN-XX` IDs come from? Sample: raw C++ for a `const char*` |
| `cases[].expected.return.value` | ✅ 🟡 | symbolic today; literal needs path solving |
| `cases[].expected.globals[]` | 🟡 | dropped by the export |
| `cases[].expected.class_members[]` | 🟡 🔍 D2 | as above |
| `cases[].expected.stub_params[]` | 🟡 | path solving |
| `cases[].expected.*.derived_from` | 📥 | requirement ID |
| `cases[].steps[]` | ➖ | IT |
