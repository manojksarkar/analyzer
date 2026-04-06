#pragma once

// =============================================================================
// Module  : app_services (hub portion)  |  Group: application
// Purpose : Cross-module integration hub — single function that depends on
//           multiple other modules, exercising wide call-graph fan-out.
// Edge cases covered:
//   - hubCompute is called by app_core (main.cpp) and calls into hal_math,
//     hal_driver, mw_types — one node with 5+ incoming/outgoing arcs
//   - Interface table: single PUBLIC entry, direction In (no global writes)
//   - Behaviour diagram: shows hubCompute connected to all callee modules
//   - Used to verify that the behaviour diagram handles high-fan-out nodes
//     without duplicating arcs or missing cross-group edges
// =============================================================================

/// Integration hub: calls multiple modules. Direction: In.
PUBLIC int hubCompute(int a, int b);
