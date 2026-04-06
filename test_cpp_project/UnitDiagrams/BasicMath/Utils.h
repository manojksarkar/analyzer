#pragma once

// =============================================================================
// Module  : hal_math  |  Group: hal
// Purpose : Hardware-abstraction-layer math utilities — simplest possible module.
// Edge cases covered:
//   - Basic function signatures (int params, int return)
//   - PUBLIC / PROTECTED visibility on free functions
//   - Internal call chain: computeBoth -> add + subtract (behaviour diagram
//     shows both caller and callee arcs within the same unit)
//   - Cross-module dependency target: other modules (structs, direction, hub,
//     outer/inner) call into hal_math, exercising multi-module call graphs
// =============================================================================

/// Add two integers. Direction: In (reads no globals).
PUBLIC int add(int a, int b);

/// Subtract b from a. Direction: In.
PUBLIC int subtract(int a, int b);

/// Compute both add and subtract, returning their sum.
/// Internal call chain: computeBoth -> add, subtract.
PROTECTED int computeBoth(int a, int b);
