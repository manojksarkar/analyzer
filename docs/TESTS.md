# Test Inventory

**349 tests total** — 235 unit · 114 integration · 0 e2e (in count below) · 7 xfail (pending real LLM generators)

> Note: e2e tests (`test_docx.py`) are listed at the bottom. The 235 unit count includes all xfailed tests.

Run commands:
```bash
pytest tests/unit/        # instant, no pipeline
pytest tests/integration/ # pipeline runs once
pytest tests/e2e/         # pipeline runs once
pytest tests/             # everything
```

Coverage: **~69–76% total** (full suite with pipeline). Unit-only: ~26%.
Subprocess coverage is captured via `sitecustomize.py` + `COVERAGE_PROCESS_START` — no manual setup needed.
See `.coveragerc` and `tests/coverage_html/index.html` for the full report.

---

## Unit tests (`tests/unit/`)

No pipeline, no network. All dependencies mocked or synthetic.

### test_behaviour_diagram_generator.py

**TestExternalCallerFiltering**
- `test_external_caller_produces_mmd_file` — caller from different module → .mmd created
- `test_internal_caller_produces_no_file` — caller from same module → skipped
- `test_no_callers_returns_empty_list` — function with no callers → []
- `test_multiple_external_callers_produce_multiple_files` — two external callers → two files

**TestFileNaming**
- `test_files_use_double_underscore_separator` — filenames contain `__`
- `test_files_have_mmd_extension` — files end with `.mmd`
- `test_pipe_chars_sanitized_in_filename` — no `|` chars in filename

**TestMmdContent**
- `test_mmd_files_are_non_empty` — .mmd files are not empty
- `test_mmd_files_contain_valid_mermaid` — content is a valid Mermaid diagram

**TestLlmContract** *(xfail — activate when real generator wired)*
- `test_llm_response_written_to_mmd` — LLM response written to file
- `test_code_fences_stripped_from_llm_response` — ` ```mermaid ``` ` fences stripped
- `test_fallback_on_empty_llm_response` — empty LLM response → fallback Mermaid diagram

### test_cli.py

**TestResolveGroupName**
- `test_exact_match` — exact group name resolves
- `test_case_insensitive_match` — lowercase/uppercase/mixed resolve to canonical
- `test_no_match_returns_none` — unknown group → None
- `test_none_requested_returns_none` — None input → None
- `test_empty_groups_returns_none` — empty groups dict → None
- `test_none_groups_returns_none` — None groups → None
- `test_exact_match_preferred_over_casefold` — when two keys differ only by case, exact match wins

**TestRunPyCli**
- `test_selected_group_requires_name` — `--selected-group` with no value → exit 1
- `test_invalid_from_phase_rejected` — `--from-phase 9` → exit 1
- `test_unknown_group_exits_2_and_lists_valid_groups` — unknown group → exit 2 + lists valid groups

### test_flowchart_generator.py

**TestFunctionIdToUnitKey**
- `test_standard_key` — `module|unit|name|params` → `module|unit`
- `test_two_part_key` — two-part key returned as-is
- `test_single_part_falls_back` — no pipe → `unknown|unknown`
- `test_empty_string` — empty → `unknown|unknown`

**TestSafeFilename**
- `test_replaces_unsafe_chars` — pipe and unsafe chars replaced
- `test_plain_name_unchanged` — safe name unchanged
- `test_empty_string` — empty → empty

**TestBuildFlowchartForFunction** *(xfail — activate when real generator wired)*
- `test_returns_llm_response` — returns LLM text verbatim
- `test_strips_code_fences` — ` ```mermaid ``` ` fences stripped
- `test_fallback_on_empty_llm_response` — empty response → fallback valid Mermaid
- `test_prompt_contains_source_code` — source code appears in LLM prompt

**TestRun**
- `test_creates_one_file_per_unit` — one JSON file per unit in output dir
- `test_output_is_list_of_name_flowchart` — each file is `[{name, flowchart}]`
- `test_function_count_matches` — correct number of entries per unit
- `test_function_names_are_simple_not_qualified` — `MyClass::getValue` → `getValue`
- `test_flowchart_content_is_valid_mermaid` — flowchart field is valid Mermaid
- `test_empty_functions_json_produces_no_files` — empty input → no output files

### test_llm_client.py

**TestLoadAbbreviations**
- `test_colon_format` — `KEY: value` parsed correctly
- `test_equals_format` — `KEY=value` parsed correctly
- `test_comments_ignored` — `#` lines skipped
- `test_blank_lines_ignored` — blank lines skipped
- `test_missing_file_returns_empty` — non-existent file → `{}`
- `test_no_path_in_config_returns_empty` — no path in config → `{}`

**TestExtractSource**
- `test_extracts_correct_lines` — line range extracted correctly
- `test_single_line` — single-line extraction
- `test_missing_file_returns_empty` — non-existent file → `""`
- `test_invalid_line_range_returns_empty` — endLine < line → `""`

**TestOllamaAvailable**
- `test_returns_true_when_200` — HTTP 200 → True
- `test_returns_false_when_not_200` — HTTP 500 → False
- `test_returns_false_on_connection_error` — connection error → False
- `test_returns_false_when_requests_not_installed` — no requests module → False

**TestCallOllama**
- `test_returns_response_text` — returns LLM response text
- `test_strips_whitespace_from_response` — leading/trailing whitespace stripped
- `test_retries_on_empty_response` — empty response → retries once
- `test_returns_empty_after_two_empties` — two empty responses → `""`
- `test_returns_empty_when_requests_not_installed` — no requests → `""`
- `test_retries_on_request_exception` — network error → retries once
- `test_uses_correct_model_from_config` — model name from config passed to API
- `test_uses_num_ctx_from_config` — numCtx from config passed to API

**TestGetDescription**
- `test_returns_llm_response` — returns LLM text
- `test_returns_empty_for_empty_source` — empty source → `""`
- `test_prompt_contains_source` — source code in prompt
- `test_prompt_includes_callee_descriptions` — callee descriptions in prompt
- `test_prompt_includes_abbreviations` — abbreviations in prompt

**TestGetBehaviourNames**
- `test_parses_well_formed_response` — `Input Name: X\nOutput Name: Y` parsed
- `test_case_insensitive_parsing` — lowercase `input name:` accepted
- `test_returns_empty_dict_on_empty_response` — empty response → `{}`
- `test_returns_empty_dict_on_unparseable_response` — garbage response → `{}`
- `test_returns_partial_if_only_one_line` — one line → partial result
- `test_returns_empty_for_empty_source` — empty source → `{}`
- `test_prompt_includes_params` — param names in prompt
- `test_prompt_includes_globals_read` — globals read in prompt
- `test_prompt_includes_abbreviations` — abbreviations in prompt

**TestGetGlobalDescription**
- `test_returns_llm_response` — returns LLM text
- `test_returns_empty_for_empty_source` — empty source → `""`
- `test_prompt_contains_source` — source in prompt

### test_model_deriver.py

**TestIdSeg**
- `test_keeps_uppercase_letters` — uppercase letters preserved
- `test_strips_digits_and_underscores` — digits and underscores removed
- `test_strips_spaces` — spaces removed
- `test_empty_string` — empty → empty
- `test_none` — None → empty
- `test_all_non_letters` — all non-letter input → empty

**TestReadableLabel**
- `test_strips_g_prefix` — `g_count` → `Count`
- `test_strips_s_prefix` — `s_value` → `Value`
- `test_strips_t_prefix` — `t_result` → `Result`
- `test_no_prefix_capitalizes` — `myVar` → `My Var`
- `test_underscores_become_spaces` — `my_var_name` → `My Var Name`
- `test_short_name_returns_empty` — single char after strip → empty
- `test_empty_returns_empty` — empty → empty
- `test_none_returns_empty` — None → empty

**TestPropagateGlobalAccess**
- `test_direct_reads_unchanged` — direct reads not modified
- `test_transitive_read_propagated` — callee reads propagated to caller
- `test_transitive_write_propagated` — callee writes propagated to caller
- `test_multi_hop_propagation` — A→B→C: A gets C's globals transitively
- `test_no_globals_produces_no_transitive_fields` — no globals → no transitive fields
- `test_does_not_include_self_call` — self-recursive call not double-counted

**TestEnrichBehaviourNames**
- `test_uses_first_param_as_input` — first param name used as input name
- `test_uses_return_expr_as_output` — return expression token used as output name
- `test_uses_global_read_when_no_params` — global read used when no params
- `test_fallback_to_function_name` — function name used as last resort
- `test_short_param_name_skipped` — single-char param skipped
- `test_output_uses_non_primitive_return_type` — struct return type used as output
- `test_fields_always_set` — both fields always populated (never empty)

**TestEnrichInterfaces**
- `test_interface_id_starts_with_IF` — `IF_` prefix present
- `test_interface_id_contains_project_code` — project code in ID
- `test_interface_id_contains_group_code` — group code in ID
- `test_interface_id_index_zero_padded` — index is zero-padded (e.g. `01`)
- `test_non_letter_chars_stripped_from_project` — special chars removed from all segments

### test_interface_tables_view.py

**TestStripExt**
- `test_removes_cpp_extension` — `file.cpp` → `file`
- `test_removes_h_extension` — `header.h` → `header`
- `test_no_extension_unchanged` — `noext` → `noext`
- `test_none_returns_none` — None → None
- `test_empty_string` — empty → empty
- `test_dotfile_treated_as_extension` — `.hidden` → `.hidden`

**TestFidToUnit**
- `test_maps_fid_to_unit` — functionId → set of owning unit keys
- `test_fid_in_multiple_units` — fid in two units → union
- `test_empty_units` — empty input → `{}`
- `test_unit_with_no_function_ids` — unit with no functions → `{}`

**TestBuildInterfaceTables**
- `test_empty_model_returns_unit_names` — always has `unitNames` key
- `test_skips_non_cpp_units` — `.h` units excluded
- `test_includes_cpp_unit` — `.cpp` units included
- `test_unit_names_populated` — unit display names correct
- `test_public_function_included` — public function appears in entries
- `test_private_function_excluded` — private function absent
- `test_missing_function_id_skipped` — missing fid gracefully skipped
- `test_global_variable_included` — public global appears, gets range
- `test_private_global_excluded` — private global absent
- `test_allowed_modules_filters_out_other_modules` — other modules excluded
- `test_function_entry_has_expected_keys` — all required keys present
- `test_file_extension_stripped_in_location` — `.cpp` stripped from `location.file`
- `test_caller_unit_appears_in_source_dest` — external callers in sourceDest
- `test_function_parameters_get_range` — parameters enriched with range
- `test_description_added_when_present` — description key added when set
- `test_no_description_key_when_absent` — no description key when unset
- `test_functions_sorted_by_line` — entries sorted by line number

### test_unit_diagrams_view.py

**TestUnitPartId**
- `test_pipe_replaced_by_underscore` — `Mod|core` → `Mod_core`
- `test_space_replaced_by_underscore` — `My Module` → `My_Module`
- `test_empty_string_returns_u` — empty → `u`
- `test_none_returns_u` — None → `u`
- `test_no_special_chars_unchanged` — plain name unchanged

**TestEscapeLabel**
- `test_double_quotes_replaced_by_single` — `"` → `'`
- `test_newline_replaced_by_space` — `\n` → space
- `test_pipe_replaced_by_broken_bar` — `|` → `¦`
- `test_empty_string` — empty → empty
- `test_none` — None → empty
- `test_plain_text_unchanged` — safe text unchanged

**TestFidToUnitDiagrams**
- `test_maps_fid_to_first_unit` — fid → first unit key (first-wins)
- `test_fid_first_unit_wins` — dict insertion order determines winner
- `test_empty_units` — empty → `{}`

**TestBuildUnitDiagram**
- `test_non_cpp_unit_returns_none` — `.h` unit → None
- `test_cpp_unit_returns_string` — `.cpp` unit → string
- `test_output_starts_with_mermaid_init` — starts with `%%{init:`
- `test_output_contains_flowchart_lr` — `flowchart LR` present
- `test_output_contains_subgraph_for_module` — `subgraph` present
- `test_unit_node_appears_in_diagram` — unit node ID in output
- `test_callee_edge_labeled_with_interface_id` — cross-unit edge labeled with interfaceId
- `test_self_calls_not_added_as_edges` — intra-unit calls omitted
- `test_allowed_modules_marks_internal_units` — allowed_modules scope applied

### test_views_registry.py

**TestViewRegistry**
- `test_register_adds_to_registry` — `@register("name")` inserts into VIEW_REGISTRY
- `test_register_stores_original_function` — stored function is callable
- `test_register_returns_original_function_unchanged` — decorator returns original fn
- `test_multiple_views_registered` — multiple views coexist
- `test_registry_starts_empty` — fresh module import has empty registry

**TestResolveScript**
- `test_empty_script_path_returns_default` — empty → `fake_flowchart_generator.py`
- `test_none_script_path_returns_default` — None → `fake_flowchart_generator.py`
- `test_absolute_path_returned_as_is` — absolute path unchanged
- `test_relative_path_joined_to_project_root` — relative path joined to project root

### test_utils.py

**TestStripJsonComments**
- `test_line_comment_removed` — `// comment` removed
- `test_block_comment_removed` — `/* comment */` removed
- `test_url_in_string_preserved` — `"http://..."` not stripped
- `test_comment_marker_in_string_preserved` — `"//"` inside string preserved
- `test_no_comments_unchanged` — clean JSON unchanged
- `test_multiline_block_comment` — multiline `/* */` removed
- `test_empty_string` — empty input → empty

**TestStripTrailingCommas**
- `test_trailing_comma_before_brace` — `,}` → `}`
- `test_trailing_comma_before_bracket` — `,]` → `]`
- `test_comma_in_string_preserved` — comma inside string not removed
- `test_non_trailing_comma_preserved` — mid-array comma preserved
- `test_nested_trailing_commas` — nested trailing commas all removed
- `test_empty_string` — empty input → empty

**TestLoadConfig**
- `test_loads_json_with_comments` — comments stripped before parse
- `test_loads_json_with_trailing_comma` — trailing commas stripped before parse
- `test_local_override_merges` — local config values override base config
- `test_missing_config_returns_empty` — missing file → `{}`

**TestSafeFilename**
- `test_pipe_replaced` — `|` → `_`
- `test_slashes_replaced` — `/` and `\` → `_`
- `test_safe_string_unchanged` — alphanumeric unchanged
- `test_none_returns_empty` — None → `""`
- `test_special_chars_replaced` — `<>:"/\|?*` replaced

**TestShortName**
- `test_qualified_name` — `MyClass::getValue` → `getValue`
- `test_deeply_nested` — `A::B::C::d` → `d`
- `test_plain_name` — no `::` → unchanged
- `test_empty` — empty → empty
- `test_none` — None → `""`

**TestGetRangeForType** *(parametrized)*
- Known types: `void`, `bool`, `int`, `unsigned int`, `uint8_t`, `uint16_t`, `uint32_t`, `int8_t`, `int16_t`, `int32_t`, `float`, `std::uint8_t`, `size_t`, `SomeStruct*`, empty string
- `test_const_qualified` — `const int` → same range as `int`
- `test_void_pointer_is_not_void` — `void*` → NA, not VOID

**TestMakeUnitKey**
- `test_resolves_module_from_path` — path maps to correct module
- `test_unit_name_is_filename_without_extension` — `Core.cpp` → unit name `Core`
- `test_unknown_path_returns_unknown` — unmapped path → `unknown|unknown`
- `test_empty_path` — empty path → `unknown|unknown`

**TestGetRange**
- `test_empty_type_returns_na` — empty type → `NA`
- `test_none_type_returns_na` — None type → `NA`
- `test_empty_dict_falls_back_to_get_range_for_type` — `uint8_t` with no dict → `0-0xFF`
- `test_direct_key_lookup_returns_range` — exact dict key match → range
- `test_direct_key_lookup_case_insensitive` — lowercase key matched case-insensitively
- `test_qualified_name_lookup` — `qualifiedName` field searched
- `test_typedef_resolves_underlying_type` — `kind=typedef` follows `underlyingType`
- `test_typedef_chain_resolved` — multi-hop typedef chain resolved
- `test_typedef_with_no_underlying_returns_na` — empty underlyingType → `NA`
- `test_typedef_depth_guard` — circular typedef chain terminates, returns `NA`
- `test_entry_with_range_preferred_over_typedef` — explicit `range` wins over typedef resolution
- `test_pointer_type_strips_star` — `MyStruct*` → looks up `MyStruct`
- `test_ref_type_strips_ampersand` — `MyStruct&` → looks up `MyStruct`
- `test_const_qualified_strips_const` — `const Speed` → looks up `Speed`
- `test_unknown_type_not_in_dict_returns_na` — unknown type not in dict → `NA`

---

## Integration tests (`tests/integration/`)

Pipeline runs once before all tests. Tests read `model/` and `output/` artifacts.

### test_model_json.py

- `test_functions_json_not_empty` — `model/functions.json` is non-empty
- `test_function_key_format` — keys are `module|unit|qualifiedName|paramTypes`
- `test_function_required_fields` — all required fields present on every function
- `test_function_location_has_file_and_line` — `location.file` and `location.line` set
- `test_phase2_enrichment_present` — `interfaceId` (IF_ prefix) and `direction` set
- `test_interface_ids_unique` — no duplicate interfaceIds within Sample
- `test_behaviour_names_set` — `behaviourInputName`/`behaviourOutputName` non-empty for public functions
- `test_global_variables_json_not_empty` — `model/globalVariables.json` is non-empty
- `test_global_variable_key_format` — keys are `module|unit|qualifiedName`
- `test_global_variable_required_fields` — required fields present on every global
- `test_units_json_not_empty` — `model/units.json` is non-empty
- `test_sample_units_present` — Core, Lib, Util all present
- `test_unit_required_fields` — required fields on every unit
- `test_unit_function_ids_are_strings` — function ID lists contain strings
- `test_core_calls_lib_and_util` — Core unit has Lib and Util in calleeUnits
- `test_util_has_no_callees` — Util has no calleeUnits
- `test_modules_json_not_empty` — `model/modules.json` is non-empty
- `test_sample_modules_present` — Core, Lib, Util modules present
- `test_module_has_units_list` — each module has non-empty units list

### test_interface_tables.py

- `test_unit_names_present` — `unitNames` key present in output
- `test_expected_units_present` — Core, Lib, Util all in output
- `test_unit_names_map` — unitNames maps unit keys to display names
- `test_unit_has_entries[*]` *(parametrized)* — Core/Lib/Util each have entries
- `test_required_fields_present` — every entry has interfaceId, type, name, unitKey, unitName, direction
- `test_interface_ids_start_with_IF` — every interfaceId starts with `IF_`
- `test_entry_types_valid` — type is `Function` or `Global Variable`
- `test_private_functions_excluded` — coreHelper, coreSwitch, libClamp, utilClip absent
- `test_private_globals_excluded` — `g_count` absent
- `test_function_direction[coreGetCount-Out]` — read-only function → Out
- `test_function_direction[coreSetResult-In]` — write function → In
- `test_function_direction[utilCompute-Out]` — read-only → Out
- `test_function_direction_values_valid` — all function directions are In or Out
- `test_global_variable_direction_is_inout` — all globals have direction In/Out
- `test_public_functions_present[*]` *(parametrized)* — all public functions present per unit
- `test_public_global_present[*]` *(parametrized)* — g_result, g_utilBase present
- `test_snapshot` — full JSON matches golden `tests/snapshots/Sample/interface_tables.json`

### test_unit_diagrams.py

- `test_expected_mmd_files_exist` — Core_Core.mmd, Lib_Lib.mmd, Util_Util.mmd all exist
- `test_flowchart_direction_is_lr[*]` *(parametrized)* — each .mmd starts with `flowchart LR`
- `test_subgraph_present[*]` *(parametrized)* — each .mmd contains a `subgraph`
- `test_subgraph_label_matches_module[*]` *(parametrized)* — subgraph label matches module name
- `test_main_unit_has_main_unit_class[*]` *(parametrized)* — main unit node has `mainUnit` class
- `test_peer_not_styled_as_main_unit[*]` *(parametrized)* — peer units not styled as mainUnit
- `test_cross_module_edge_with_if_label[*]` *(parametrized)* — cross-module edges labeled with IF_ IDs
- `test_util_never_initiates_cross_module_call` — Util has no outgoing cross-module edges
- `test_core_has_no_incoming_cross_module_callers` — Core has no external callers within Sample
- `test_snapshot` — all .mmd content matches golden `tests/snapshots/Sample/unit_diagrams.json`

### test_behaviour_diagram.py

- `test_behaviour_diagrams_dir_exists` — `output/behaviour_diagrams/` directory exists
- `test_behaviour_pngs_json_exists` — `_behaviour_pngs.json` exists
- `test_mmd_files_exist` — at least one .mmd file present
- `test_docx_rows_key_present` — `_docxRows` key in JSON
- `test_core_has_docx_rows` — Core has behaviour rows (external callers: App/Main, Cross/Hub)
- `test_lib_has_no_docx_rows` — Lib has no rows (only internal callers)
- `test_util_has_no_docx_rows` — Util has no rows (only internal callers)
- `test_docx_row_fields` — every row has currentFunctionName, externalUnitFunction, pngPath
- `test_external_unit_function_format` — `externalUnitFunction` is `"UnitName - funcName"`
- `test_core_external_callers_are_outside_sample` — Core callers not from Core/Lib/Util
- `test_mmd_files_use_double_underscore_separator` — filenames contain `__`
- `test_mmd_files_contain_valid_mermaid` — content is valid Mermaid (any diagram type)

### test_flowcharts.py

- `test_flowcharts_dir_exists` — `output/flowcharts/` directory exists
- `test_flowchart_file_exists[*]` *(parametrized)* — Core.json, Lib.json, Util.json all exist
- `test_flowchart_file_is_list[*]` *(parametrized)* — each file is a JSON array
- `test_flowchart_file_not_empty[*]` *(parametrized)* — each file is non-empty
- `test_entries_have_name_and_flowchart[*]` *(parametrized)* — every entry has `name` and `flowchart`
- `test_flowchart_strings_are_valid_mermaid[*]` *(parametrized)* — flowchart is valid Mermaid (code fences stripped before check)
- `test_function_names_are_nonempty[*]` *(parametrized)* — no blank function names
- `test_expected_functions_present[*]` *(parametrized)* — all expected public functions present per unit

### test_behaviour_names.py

- `test_functions_json_has_phase2_fields` — at least one function has behaviourInputName set
- `test_all_public_functions_have_behaviour_input_name` — every public function has non-empty input name
- `test_all_public_functions_have_behaviour_output_name` — every public function has non-empty output name
- `test_behaviour_names_are_strings` — both fields are always strings
- `test_description_field_is_string_when_llm_off` — description is string (empty when LLM off)
- `test_static_behaviour_name_derivation[*]` *(parametrized)* — known derivations: coreGetCount→Count, coreLoopSum→Sum, coreOrchestrate→Sum
- `test_return_expr_heuristic_produces_non_generic_output` — returnExpr path fires correctly
- `test_global_read_heuristic_for_getter_function` — global read prevents generic fallback

---

## E2E tests (`tests/e2e/`)

Pipeline runs once. Tests open `output/software_detailed_design_Sample.docx` with python-docx.

### test_docx.py

- `test_docx_exists` — DOCX file exists
- `test_docx_non_empty` — DOCX has at least one paragraph
- `test_interface_tables_found_in_docx` — at least one interface table present
- `test_interface_table_has_data_rows` — tables have data rows beyond the header
- `test_interface_ids_start_with_IF` — all IF_ IDs in tables start with `IF_`
- `test_interface_type_values_valid` — interface type column contains valid values
- `test_private_names_absent_from_docx` — private function names not in DOCX
- `test_public_name_in_docx[*]` *(parametrized)* — all public function/global names appear in DOCX
- `test_direction_in_docx[*]` *(parametrized)* — coreGetCount→Out, coreSetResult→In, g_result→In/Out
- `test_docx_has_embedded_images` — at least one image embedded
- `test_all_unit_headings_found_in_docx` — Core, Lib, Util headings present
- `test_unit_diagram_image_placed_after_heading[*]` *(parametrized)* — unit diagram PNG after heading for each unit
- `test_heading_present[Dynamic Behaviour]` — Dynamic Behaviour section present
- `test_heading_present[Static]` — Static section present
- `test_introduction_section_headings[*]` *(parametrized)* — Purpose, Scope, Terms headings present
- `test_module_level1_heading_present[*]` *(parametrized)* — Core/Lib/Util level-1 headings
- `test_code_metrics_heading_present` — Code Metrics heading present
- `test_appendix_heading_present` — Appendix heading present
- `test_dynamic_behaviour_sub_headings_for_core` — Core external caller headings in Dynamic Behaviour
- `test_behaviour_description_tables_present` — behaviour description tables in DOCX
- `test_flowchart_tables_present` — flowchart tables in Static Design section
- `test_component_unit_table_present` — Component/Unit table with correct headers
- `test_component_unit_table_has_module_names` — Core/Lib/Util present in table
- `test_unit_header_table_present` — unit header table with global/typedef/enum/define header
- `test_module_static_diagram_content_present` — module static diagram PNG or Mermaid text present
