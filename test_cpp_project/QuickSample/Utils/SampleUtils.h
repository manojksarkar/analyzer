#pragma once

// =============================================================================
// Module  : QsUtils  |  Group: QuickSample
// Purpose : Utility helpers called by QsCore — creates cross-module call arcs
//           for the behaviour diagram within the QuickSample group.
// Edge cases covered:
//   - Called by multiple functions in QsCore (fan-in from Core to Utils)
//   - PUBLIC functions appear as targets in behaviour diagram arcs
//   - PRIVATE function (qsClamp) excluded from behaviour diagram nodes
//     but shown as private callee flowchart under qsNormalize
// =============================================================================

/// Adds two values. Called by sampleAdd and sampleOrchestrate (multiple callers).
PUBLIC int qsAdd(int a, int b);

/// Clamps value to [0, max]. PRIVATE — excluded from behaviour diagram nodes.
PRIVATE int qsClamp(int value, int max);

/// Normalizes value to [0, 100] using qsClamp (private callee flowchart).
PUBLIC int qsNormalize(int value, int max);
