# UT templates

Templates of the two UT-automation JSON files. Readiness → [UT_EXPORT_READINESS](../UT_EXPORT_READINESS.md).

| File | Holds |
|---|---|
| [testcase.template.json](testcase.template.json) | One test environment's cases |
| [hierarchy.template.json](hierarchy.template.json) | Layers → sections → test environments |

Format unchanged from the sample (photos, 2026-09-23); no key added or removed.

## Check a file

`python tools/check_ut_json.py <file.json> [more.json ...]` — template picked from the content;
exit code 1 on any ERROR. ERROR = wrong type, unknown or missing required key · WARN = value
outside a closed set · INFO = optional key absent, empty value, placeholder left in, IT skipped.

## Reading them

| In the template | Means |
|---|---|
| `<...>` | placeholder |
| Dict whose keys are all `<...>` | map — any key |
| Key in every example | required (in only some → optional) |
| Literal string | example — except the closed sets: `level`, `stubs[].mode`, `probepoint[].position`, `escape_hatch.language` / `kind` |
| Scalar value | string (`"<value>"`); booleans, `null`, arrays, structs as shown |
| Project names | placeholders — user config (Sample: `Layer1`, `Core1`) |
| `<CORE_NAME_n>` | has its `<CORE_NAME_n>Macros` entry |
| `<external_search_directory>` | a directory outside the project |
| IT case `<TEST-CASE-ID-004>` | part of the format; out of scope (SWE.2) |

## Changes from the sample

| Change | Why |
|---|---|
| Core names, `SectionID`, `EnvironmentId`, directory paths → placeholders | project-specific (sample: HCore/FCore/NCore/SED, `ABC1`, `PQR1`, `…\HAL\Inc`) |
| `review` on every case | sample: 2 of 4 cases |
| Destructor `expected` = the constructor's four keys | sample: `{}` |
| IT step 2 gets `preconditions` | as step 1 |
| Probe point `"position": "after"` | the format's guide describes before and after |
| Header test environment (`IsHeader: true`) | sample: only `false` |
