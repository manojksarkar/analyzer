# Test Inventory

Which test checks which [SWE3_WIKI](SWE3_WIKI.md) rule, so a review comment on a rule can be answered
with the test that guards it — or with "not tested".

```bash
python -m pytest tests/unit tests/api tests/e2e          # everything that needs no real database
python -m pytest tests/unit tests/api tests/e2e --collect-only -q | tail -1   # how many tests
```

| Folder | What it is |
|---|---|
| `tests/unit/` | No pipeline, no network. One file per behaviour; the file name says which |
| `tests/api/` | The HTTP API, with its database replaced |
| `tests/e2e/` | The pipeline runs once on `SampleCppProject`; each file checks one output: `test_model_json` (the model), `test_interface_tables`, `test_unit_headers`, `test_unit_diagrams`, `test_flowcharts` (view output), `test_docx` (the Word file), `test_test_specs` (SWE.4) |
| `tests/live/` | Needs a real PostgreSQL database |

A test below is in the file named in its section's heading, unless the row names another; `(unit)`
means `tests/unit/`. A file or class name stands for every test in it.

---

## Rule coverage, by SWE3_WIKI rule id

A rule not listed has no test named here yet.

### DOC — the document as a whole · `tests/e2e/test_docx.py`

| Rule | Test | Checks |
|---|---|---|
| SWE3-DOC-03 | `test_introduction_section_headings`, `test_component_level1_heading_present`, `test_code_metrics_heading_present`, `test_appendix_heading_present` | the top-level sections |
| SWE3-DOC-05 | `test_heading_present` (Static, Dynamic Behaviour) | a component's two parts |
| SWE3-DOC-06 | `test_all_unit_headings_found_in_docx`, `test_unit_diagram_image_placed_after_heading`, `test_unit_header_table_present` | a unit's sub-section and its order |
| SWE3-DOC-08 | `test_skips_non_cpp_units`, `test_includes_cpp_unit` (unit, `test_interface_tables_view.py`) | a header with no source file gets no table |
| SWE3-DOC-12 | `test_allowed_components_filters_out_other_components` (unit, `test_interface_tables_view.py`) | other components' units get no table |
| SWE3-DOC-14 | `test_model_order_is_deterministic.py` (unit) | the same code gives the same order |

### SD — Static diagram: component diagrams and table · `tests/e2e/test_docx.py`

| Rule | Test | Checks |
|---|---|---|
| SWE3-SD-01 | `test_container_diagram.py` (unit), `test_component_static_diagram_content_present` | the container diagram |
| SWE3-SD-06 | `test_component_unit_table_present`, `test_the_component_unit_table_follows_the_unit_headings` (unit, `test_doccheck_levels.py`) | the table and its columns |
| SWE3-SD-07 | `test_component_unit_table_has_component_names` | the Component column |
| SWE3-SD-09 | `test_docx_unit_descriptions.py` (unit) | the Description column |

### SD — Static diagram: unit architecture diagram · `tests/unit/test_unit_diagrams_view.py` + `tests/e2e/test_unit_diagrams.py`

| Rule | Test | Checks |
|---|---|---|
| SWE3-SD-11 | `test_non_cpp_unit_returns_none`, `test_cpp_unit_returns_string`, `test_output_contains_flowchart_lr` (unit); `test_expected_mmd_files_exist`, `test_flowchart_direction_is_lr`, `test_every_edge_has_if_label` (e2e) | one diagram per unit, left to right, every arrow labelled |
| SWE3-SD-12 | `test_owned_edge_labeled_with_interface_id`, `test_incoming_caller_edge_labeled_with_interface_id` (unit); `test_expected_partner_present`, `test_non_consumer_absent` (e2e) | only the unit's own interfaces, to their callers |
| SWE3-SD-16 | `test_multiple_ifaces_on_same_edge_both_appear`, `test_ids_of_one_group_are_tight`, `test_group_is_padded_above_and_below`, `test_every_id_survives` (unit) | one arrow, all its ids, spaced |
| SWE3-SD-18 | `test_self_calls_not_added_as_edges` (unit) | no arrow to itself |
| SWE3-SD-19 | `test_output_contains_subgraph_for_module`, `test_subgraph_labelled_with_component_name`, `test_mainunit_class_applied_to_current_unit`, `test_internal_peer_gets_internal_class`, `test_allowed_components_marks_internal_units` (unit); `test_subgraph_present`, `test_subgraph_label_matches_component`, `test_main_unit_has_main_unit_class`, `test_peer_not_styled_as_main_unit` (e2e) | the component box and who is inside it |
| SWE3-SD-20 | `test_external_caller_node_appears_before_subgraph`, `test_external_callee_node_appears_after_subgraph`, `test_mutual_external_partner_drawn_on_both_sides`, `test_mutual_internal_partner_split_within_module` (unit) | left and right of the unit |
| SWE3-SD-21 | `test_published_globals_drawn_by_name`, `test_class_static_keeps_its_class`, `test_globals_styled_and_have_no_edges`, `test_globals_share_an_inner_box_with_the_unit_inside_the_component`, `test_no_published_global_leaves_the_diagram_unchanged` (unit); `test_published_globals_drawn`, `test_globals_have_no_edges` (e2e) | the unit's published globals |
| SWE3-SD-22 | `test_private_global_not_drawn`, `test_peer_units_globals_not_drawn` (unit); `test_global_without_a_row_not_drawn` (e2e) | globals that are not drawn |
| SWE3-SD-23 | `test_pipe_replaced_by_underscore`, `test_space_replaced_by_hyphen`, `test_empty_string_returns_u`, `test_double_quotes_replaced_by_single`, `test_newline_replaced_by_space`, `test_pipe_replaced_by_broken_bar`, `test_multiple_escapes_combined`, `test_brackets_in_a_name_do_not_break_the_node` (unit) | characters that would break the picture |

### UH — Unit header · `tests/e2e/test_unit_headers.py`

| Rule | Test | Checks |
|---|---|---|
| SWE3-UH-01 | `test_every_unit_with_a_section_has_an_entry`, `test_rows_have_both_columns` | one table per unit, two columns |
| SWE3-UH-02 | `test_a_private_global_is_listed` | access decides nothing |
| SWE3-UH-11, SWE3-UH-22 | `test_unit_header_comments.py` (unit) | declarations over several lines; comments removed |
| SWE3-UH-17 | `test_a_class_static_definition_has_no_row` | a static member's definition |
| SWE3-UH-18 | `test_an_orphan_header_is_listed_once_by_its_owner`, `test_an_orphan_header_global_is_not_repeated_in_its_reader`, `test_the_owner_is_the_first_user_in_the_headers_own_component`, `test_with_no_user_in_its_component_the_first_user_by_name_owns_it`; `test_unit_header_orphan.py` (unit) | one owner per orphan header |
| SWE3-UH-19 | `test_an_orphan_symbol_nobody_uses_is_listed_nowhere` | unused orphan symbols |
| SWE3-UH-23 | `test_the_defining_unit_shows_the_definition_not_the_extern` | one variable in two files |

### UI — Unit interface · `tests/e2e/test_interface_tables.py` + `tests/unit/test_interface_tables_view.py`

| Rule | Test | Checks |
|---|---|---|
| SWE3-UI-01 | `test_expected_units_present`, `test_required_fields_present`; `test_interface_tables_found_in_docx`, `test_interface_table_has_data_rows` (`test_docx.py`) | one table per unit, every column on every row |
| SWE3-UI-03 | `test_public_functions_present`, `test_private_functions_excluded`; `test_public_function_included`, `test_private_function_excluded` (unit) | a function another unit calls |
| SWE3-UI-04 | `test_global_used_by_another_unit_present`, `test_global_used_only_by_its_own_unit_absent`; `test_a_use_through_an_extern_declaration_counts_for_the_definition`, `test_an_extern_used_only_inside_the_defining_unit_does_not_publish` (unit, `test_visibility_matrix.py`) | a global another unit uses |
| SWE3-UI-05 | `test_a_marked_function_another_unit_calls_is_published`; `test_a_marked_function_another_unit_calls_has_its_row` (`test_docx.py`); `test_no_marking_changes_the_answer`, `test_a_marking_cannot_publish_a_global` (unit, `test_visibility_matrix.py`) | no marking decides |
| SWE3-UI-07 | `test_private_globals_excluded`; `test_private_names_absent_from_docx` (`test_docx.py`) | private items have no row |
| SWE3-UI-10 | `test_function_entries_sorted_by_line`; `test_functions_sorted_by_line` (unit) | function order — by line, which is id order only while a unit's functions are in one file |
| SWE3-UI-11 | `test_interface_ids_start_with_IF`, `test_interface_id_segments_uppercase` (e2e and `test_docx.py`); `test_interface_id_contains_group_code`, `test_interface_id_index_zero_padded` (unit, `test_model_deriver.py`) | the id's shape |
| SWE3-UI-12 | `test_interface_id_contains_project_code`, `test_non_letter_chars_stripped_from_project` (unit, `test_model_deriver.py`) | no layer: the project name |
| SWE3-UI-13 | `TestInterfaceIndexUnitKeyed` (unit, `test_model_deriver.py`) | one count per unit, `.cpp` before `.h` |
| SWE3-UI-14 | `test_interface_id_uniqueness.py` (unit) | no id printed twice |
| SWE3-UI-16, SWE3-UI-17 | `test_public_name_in_docx` (`test_docx.py`); `test_function_names.py` (unit) | names; overloads print apart |
| SWE3-UI-19, SWE3-UI-20 | `test_function_rows_show_return_type` (`test_docx.py`); `test_return_type_passed_through`, `test_return_type_defaults_to_empty` (unit) | Data Type and its `return:` line |
| SWE3-UI-22 | `test_function_rows_show_return_range` (`test_docx.py`); `test_function_parameters_get_range`, `test_return_range_derived_from_return_type`, `test_return_range_defaults_to_na` (unit) | one range per Data Type line |
| SWE3-UI-23, SWE3-UI-24 | `test_data_dictionary_layers.py`, `test_data_dictionary_csv.py` (unit) | which data dictionary answers |
| SWE3-UI-27 … SWE3-UI-29 | `test_function_direction`, `test_function_direction_values_valid`; `test_direction_in_docx` (`test_docx.py`) | function direction |
| SWE3-UI-30 | `test_global_variable_direction_is_inout` | globals are `In/Out` |
| SWE3-UI-31 | `test_sourcedest_includes_cross_unit_callers`, `test_caller_units_populated`; `test_caller_unit_appears_in_source_dest` (unit); `test_source_destination_still_names_the_partner_units` (`test_docx.py`) | every other calling unit |
| SWE3-UI-33 | `test_no_layer_qualified_id_reaches_the_document` (`test_docx.py`) | the layer prefix is dropped |
| SWE3-UI-35 | `test_entry_types_valid`; `test_interface_type_values_valid` (`test_docx.py`) | `Function` or `Global Variable` |

`test_callee_units_populated` and `test_global_entries_have_empty_caller_callee` check the stored call
lists that Source/Destination is built from; the document prints neither.

### FD — Flow diagram · `tests/e2e/test_flowcharts.py`

| Rule | Test | Checks |
|---|---|---|
| SWE3-FD-01 | `test_expected_functions_present`, `test_flowchart_file_exists`, `test_function_names_are_nonempty` | an entry per public function |
| SWE3-FD-02 | `test_flowchart_tables_present` (`test_docx.py`) | the five-row table |
| SWE3-FD-06 | `test_flowchart_strings_are_dot`; `test_cfg_topo.py` (unit) | the shape comes from the code |
| SWE3-FD-08 | `test_call_name_labels.py` (unit) | every call named `Name()` |
| SWE3-FD-10 | `test_cfg_missing_header.py` (unit) | a missing header removes no branch |
| SWE3-FD-12 … SWE3-FD-14 | `TestEnrichBehaviourNames` (unit, `test_model_deriver.py`) | Input and Output Name, without the LLM |

### DB — Dynamic behaviour · `tests/e2e/test_docx.py`

| Rule | Test | Checks |
|---|---|---|
| SWE3-DB-01 | `test_the_default_filter_draws_the_gateway_rows_and_nothing_else`; `test_behaviour_diagram_external_callers.py` (unit) | which functions get an entry |
| SWE3-DB-03 | `test_dynamic_behaviour_sub_headings_for_core` | the entry heading |
| SWE3-DB-04 | `test_behaviour_description_tables_present` | the entry table |

---

## Not tested

| Rule | What | Why |
|---|---|---|
| SWE3-DOC-09 | `emul` files skipped, `.c` not read | no such file in `SampleCppProject` |
| SWE3-SD-02 … SWE3-SD-05 | the file dependency diagram | — |
| SWE3-UI-12 | the id with no group | needs a unit whose component has no group |
| SWE3-UI-18, SWE3-FD-15 | what the LLM writes | the tests run with the LLM off |
