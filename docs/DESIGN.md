# Design

## Architecture

Parse C++ → model (single source of truth) → views (interface tables, DOCX).

![Architecture](images/architecture.png)  
*Editable: `docs/images/architecture.drawio` (draw.io)*

| Component | Role | Input/Output |
|-----------|------|--------------|
| **run.py** | Orchestrator | Invokes Phase 1 → 2 → 3 in sequence |
| **parser.py** | Phase 1: Parse | C++ files → model/metadata, functions, globalVariables, dataDictionary |
| **generator.py** | Phase 2: Derive & views | Model → units, modules, enriched functions/globals, interface_tables.json |
| **docx_exporter.py** | Phase 3: Export | interface_tables.json → interface_tables.docx |

**Model (single source of truth, non-redundant for DB):** functions.json, globalVariables.json, units.json, modules.json, dataDictionary.json. Function keys/IDs: `module/unit/qualifiedName/paramTypes` where unit = full subpath (e.g. `tests/structs/point_rect`). Global keys: `module/unit/qualifiedName`. Units have `key` (subpath) and `name` (filestem for display). Call graph uses `calledByIds` and `callsIds` (function IDs). interfaceId: IF_project_unit_index.

**Views (read-only projections):** interface_tables.json, interface_tables.docx. Recomputable from model.

---

## Logic Flow

### Phase 1 – Parse (parser.py)
1. Walk project dir for `.cpp`, `.h`, `.hpp`, etc.
2. For each file: libclang parse → `visit_definitions`, `visit_type_definitions` → collect functions, globals, types (structs, enums, typedefs, primitives in dataDictionary keyed by name/qualifiedName with kind).
3. Second pass: `visit_calls` → build call graph (call_graph, reverse_call_graph).
4. Write metadata.json, functions.json, globalVariables.json, dataDictionary.json.

### Phase 2 – Derive & views (generator.py)
1. Load functions, globals, metadata.
2. `_compute_unit_maps` → file list, qualified name → file mapping, unit names.
3. `_build_units_modules` → units.json, modules.json (per-file units with callerUnits, calleesUnits).
4. `_build_interface_index` → stable per-file interface index (01, 02, …).
5. `_enrich_interfaces` → interfaceId, interfaceName, parameters (range), callerUnits, calleesUnits.
6. Optional: `_maybe_enrich_descriptions` (LLM) → description per function.
7. `_infer_direction_from_code` → direction for globals and functions (see below).
8. Persist enriched functions.json, globalVariables.json.
9. `build_interface_tables` → interface_tables.json (grouped by unit).

### Direction inference
- **Globals:** Aggregate read/write in function bodies → In / Out / In/Out / -.
- **Functions:**  
  1. Write any global → Out.  
  2. Else read any global → In.  
  3. Else calls an Out function → Out.  
  4. Else called from another unit → In.  
  5. Else default In; optional LLM refine (`enableDirectionLLM`).

### Phase 3 – Export (docx_exporter.py)
1. Load interface_tables.json.
2. Group by module → units → tables with columns (Interface ID, Interface Name, Information, Data Type, Data Range, Direction, Source/Destination, Interface Type).
3. Save DOCX.

---

## Traversals

| What | Where | How |
|------|-------|-----|
| Call graph | parser.py | `visit_calls` builds call_graph, reverse_call_graph; stored in functions.calledBy, calls |
| Direction propagation | generator.py `_infer_direction_from_code` | Traverse calleesFunctionNames; if callee is Out, mark caller Out |
| Unit/module build | generator.py `_build_units_modules` | Iterate file_paths; map qualified names → files → units; aggregate caller/callee units per unit |
| View build | interface_tables.py `build_interface_tables` | Iterate units_data; derive callerUnits/calleesUnits from calledBy/calls; resolve param range via get_range(type, dataDictionary); produce { unit: [interfaces] }. Units use functionIds, globalVariableIds. |

---

## Extensibility

New views: create a view builder that reads model (functions, globals, units, modules, dataDictionary), traverses as needed, writes output. Call it from `generator.main()` after `build_interface_tables`.
