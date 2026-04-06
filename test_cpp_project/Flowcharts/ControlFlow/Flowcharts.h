#pragma once

// =============================================================================
// Module  : app_control  |  Group: application
// Purpose : Control-flow pattern coverage — every major branching and looping
//           construct exercised by one PRIVATE function each, all wired through
//           the single PUBLIC entry-point runFlowTests().
// Edge cases covered (20 control-flow patterns):
//   1.  fnIfSimple         — single if, no else
//   2.  fnIfElse           — if/else two-branch
//   3.  fnNestedIfElse     — nested if/else (2 levels)
//   4.  fnIfElseIf         — if / else-if chain (3 branches + default)
//   5.  fnSwitchSimple     — switch with explicit break per case
//   6.  fnSwitchFallthrough — switch with intentional case fall-through
//   7.  fnForLoop          — basic counting for-loop
//   8.  fnForBreak         — for-loop with early break
//   9.  fnForContinue      — for-loop with continue (skip even)
//  10.  fnWhileLoop        — while-loop
//  11.  fnDoWhile          — do-while loop
//  12.  fnNestedFor        — nested for-loop (2D traversal)
//  13.  fnForWithIf        — for-loop body containing if/else
//  14.  fnWhileWithIf      — while-loop body containing if/else
//  15.  fnIfEarlyReturn    — multiple early-return guards (no else)
//  16.  fnMixedForSwitch   — for-loop body containing switch
//  17.  fnDeeplyNested     — 3-level nested if/else
//  18.  fnMultipleReturns  — 5 distinct return paths
//  19.  fnLoopNestedIfElse — for-loop with if/else-if/else body
//  20.  runFlowTests       — PUBLIC orchestrator: calls all 19 private fns
//                            → flowchart table shows own chart + 19 private callees
// Private functions appear in the flowchart table as private-callee charts
// but are excluded from the interface table and behaviour diagram.
// =============================================================================

/// Orchestrator: calls all 19 private control-flow functions.
/// PUBLIC — shown in interface table; its flowchart table includes all
/// private callee flowcharts (deduplication via rendered_private_fids).
PUBLIC int runFlowTests();
