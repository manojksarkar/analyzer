#pragma once

// =============================================================================
// Module  : mw_state  |  Group: middleware
// Purpose : Direction-inference edge cases — how the model_deriver assigns
//           In / Out / In-Out to functions based on global variable access.
// Edge cases covered:
//   - Global declared PUBLIC (g_readOnly): appears in unit-header table
//   - Global declared PRIVATE (g_writeOnly): excluded from unit-header table
//   - Global declared PROTECTED (g_readWrite): included in unit-header table
//   - readGlobal():  reads g_readOnly only            -> direction Out (getter)
//   - writeGlobal(): writes g_writeOnly only          -> direction In  (setter)
//   - readWriteGlobal(): reads AND writes g_readWrite -> direction In  (mutator)
//   - indirectWrite(): PRIVATE, calls writeGlobal (Out propagation through call)
//   - Cross-module call into hal_math: directionAdd -> math::add
//   - PRIVATE functions excluded from interface table and behaviour diagram
// =============================================================================

/// Read-only global state. PUBLIC — shown in unit-header globals table.
PUBLIC extern int g_readOnly;

/// Write-only internal state. PRIVATE — hidden from interface and header table.
PRIVATE extern int g_writeOnly;

/// Read-write shared state. PROTECTED — shown in unit-header globals table.
PROTECTED extern int g_readWrite;

/// Reads g_readOnly only. Direction inferred: Out (getter pattern).
PUBLIC int readGlobal();

/// Writes g_writeOnly only. PRIVATE; direction: In (setter).
PRIVATE void writeGlobal(int v);

/// Reads and writes g_readWrite. PROTECTED; direction: In (mutator).
PROTECTED int readWriteGlobal(int delta);

/// PRIVATE helper; delegates to writeGlobal — Out-direction propagation.
PRIVATE void indirectWrite(int v);

/// Cross-module dependency: calls math::add (hal_math). Direction: In.
PUBLIC int directionAdd(int a, int b);
