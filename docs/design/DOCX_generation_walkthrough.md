# DOCX Generation Walkthrough (Demo Notes)

This document explains how `software_detailed_design.docx` is created section-by-section, and which data/files drive each part.

## What generates the DOCX

1. DOCX exporter script: `src/docx_exporter.py`
2. It produces: `output/software_detailed_design_all.docx` (or per-group filename)

## Main inputs to the exporter

The exporter loads these files:

- `output/interface_tables.json` (view output; drives the module/unit/interface table content)
- `model/units.json` (used to find unit-related metadata for “unit header”)
- `model/modules.json` (indirectly; module grouping happens from keys in `interface_tables.json`)
- `model/dataDictionary.json` (used when building “unit header” type/enum/typedef snippets and for range lookups)
- `model/globalVariables.json` (used by `unit header` table content)
- `model/functions.json` (used for behaviour diagram input/output naming)
- Flowchart diagrams: `output/flowcharts/*.png` (optional, used in per-interface sections)
- Unit diagrams: `output/unit_diagrams/*.png` (optional, used before the unit header)
- Behaviour diagram metadata: `output/behaviour_diagrams/_behaviour_pngs.json` (optional; drives the “Dynamic Behaviour” sections)

## Config that affects DOCX content

Important config keys (from `config/config.json`):

- `views.moduleStaticDiagram.enabled`, `views.moduleStaticDiagram.renderPng`, `views.moduleStaticDiagram.widthInches`
- `views.flowcharts.renderPng` (controls whether flowchart PNGs are used)
- `export.docxPath`, `export.docxFontSize`

## Section-by-section creation

### 1. “Software Detailed Design” heading

Added as the document title near the top.

### 1 Introduction

The exporter adds these headings and placeholder paragraphs:

- `1 Introduction`
- `1.1 Purpose`
- `1.2 Scope`
- `1.3 Terms, Abbreviations and Definitions`

### 2 Modules (static + interface tables + dynamic behaviour)

The exporter groups units by module using keys from `interface_tables.json`, then loops:

#### 2.1 Static Design

For each module:

1. Module→units diagram
   - The exporter uses the module name and the unit names from `interface_tables.json` to build the module→units tree.
   - It renders the diagram to PNG and inserts it into the DOCX.

2. Module-level index table: Component | Unit | Description | Note
   - Each unit gets a short “Description” built from the interface descriptions in `interface_tables.json`.
   - “Note” is currently left as `N/A`.

3. Per-unit content loop
   - For each unit in the module, the exporter renders the unit header and interface table.

Each unit:

- Unit heading
- Unit diagram PNG: the exporter looks for `output/unit_diagrams/*.png` and inserts it
- Unit header section: lists globals and type declarations (typedef/enum/define) available in the unit
- Unit interface table
  - Globals: `Data Type` / `Data Range` come from `variableType` / `range`
  - Functions:
    - if `parameters` is non-empty: join parameter types/ranges into `Data Type`/`Data Range`
    - if `parameters` is empty: `Data Type = VOID` and `Data Range = NA`
- Per-interface section (one section per interface entry)
  - Includes the interface ID in the heading
  - Flowchart PNG: looks for a matching file under `output/flowcharts/` and inserts it

#### 2.2 Dynamic Behaviour

After static design for each module:

- The exporter adds a “Dynamic Behaviour” section.
- It reads behaviour rows from `output/behaviour_diagrams/_behaviour_pngs.json`.
- For each behaviour row:
  - Adds a subheader describing the current function and any external call.
  - Builds a small 2-column table of Inputs/Outputs based on `functions.json` labels.
  - Inserts the behaviour diagram PNG.

### 3 Code Metrics, Coding Rule, Test Coverage

Added as placeholders:

- `[Code metrics, coding rules and test coverage.]`

### Appendix A. Design Guideline

Added as placeholders:

- `[Design guidelines.]`

## Where “Data Type / Data Range” are decided

During DOCX rendering of the unit interface table:

- Globals: `variableType` and `range`
- Functions: parameter-based
  - If `iface["parameters"]` is empty:
    - `Data Type = "VOID"`
    - `Data Range = "NA"`
  - Otherwise:
    - `Data Type` joins all `p.type`
    - `Data Range` joins all `p.range`

Other interface-table columns are populated directly:

- `Information`: uses the interface description
- `Direction`: uses the interface direction
- `Source/Destination`: uses `sourceDest`
- `Interface Type`: uses `type`

## How to regenerate (for the demo)

1. Generate model and views (pipeline)
2. Then re-run DOCX export:
   - `python src/docx_exporter.py`

