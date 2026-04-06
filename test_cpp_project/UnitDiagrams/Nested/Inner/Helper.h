#pragma once

// =============================================================================
// Module  : hal_driver  |  Group: hal
// Purpose : Low-level driver helpers — exercises deeply nested directory layout.
// Edge cases covered:
//   - Nested folder structure (outer/inner/): verifies that the parser correctly
//     resolves module keys from multi-level relative paths
//   - Cross-module call into hal_math: helperCompute -> math::add
//     (inter-group dependency visible in interface tables and call graphs)
//   - PROTECTED visibility on an internal helper (nestedHelper)
//   - PUBLIC visibility on the exported entry-point (helperCompute)
// =============================================================================

/// Internal range validator — PROTECTED (not exported in interface table).
PROTECTED int nestedHelper(int x);

/// Driver compute entry-point. Calls math::add (cross-module dependency).
PUBLIC int helperCompute(int x);
