#pragma once

// =============================================================================
// Module  : QsCore  |  Group: QuickSample
// Purpose : Compact module covering almost all edge cases in <= 10 functions.
// Edge cases covered:
//   Interface Table:
//     - Enum as parameter and return type (SampleStatus)
//     - Struct as parameter by value (SamplePoint)
//     - PUBLIC global shown in unit-header table (g_sampleResult)
//     - PRIVATE global excluded from unit-header table (g_sampleCounter)
//     - PRIVATE functions excluded from interface table (sampleHelper, sampleSwitch)
//     - PROTECTED function included in interface table (sampleGetCounter)
//     - Direction Out: sampleGetCounter reads g_sampleCounter (getter)
//     - Direction In:  sampleSetResult writes g_sampleResult (setter)
//   Flowcharts:
//     - if/else branch:  sampleCompute
//     - for loop:        sampleLoopSum
//     - switch/case:     sampleSwitch (PRIVATE — appears as private callee chart)
//     - Private callee:  sampleOrchestrate calls sampleHelper + sampleSwitch
//   Behaviour Diagram:
//     - sampleAdd -> qsAdd (QsCore -> QsUtils arc)
//     - sampleCompute -> qsNormalize (QsCore -> QsUtils arc)
//     - sampleOrchestrate -> qsAdd + qsNormalize (fan-out to QsUtils)
//     - Multiple callers of qsAdd: sampleAdd, sampleOrchestrate (fan-in to QsUtils)
//   Unit Diagram:
//     - All 10 functions + 2 globals rendered in unit diagram
// =============================================================================

enum SampleStatus { SAMPLE_OK = 0, SAMPLE_ERR = 1 };

struct SamplePoint { int x; int y; };

PUBLIC extern int g_sampleResult;
PRIVATE extern int g_sampleCounter;

/// Delegates to qsAdd (QsUtils) — cross-module arc in behaviour diagram. Direction: In.
PUBLIC int sampleAdd(int a, int b);

/// Enum param + return — type system coverage. Direction: In.
PUBLIC SampleStatus sampleCheck(SampleStatus s);

/// Struct param by value — type system coverage. Direction: In.
PUBLIC int samplePointSum(SamplePoint p);

/// Reads g_sampleCounter only — direction Out (getter). PROTECTED.
PROTECTED int sampleGetCounter();

/// Writes g_sampleResult — direction In (setter). PUBLIC.
PUBLIC void sampleSetResult(int v);

/// PRIVATE helper with if/else — excluded from interface table; appears as
/// private callee flowchart under sampleCompute and sampleOrchestrate.
PRIVATE int sampleHelper(int x);

/// Calls sampleHelper (private callee) + qsNormalize (cross-module arc). Direction: In.
PUBLIC int sampleCompute(int x);

/// For loop — flowchart loop pattern. Direction: In.
PUBLIC int sampleLoopSum(int n);

/// PRIVATE switch — excluded from interface; private callee chart under sampleOrchestrate.
PRIVATE int sampleSwitch(int op);

/// Orchestrator: calls sampleHelper + sampleSwitch (private callee charts),
/// qsAdd + qsNormalize (cross-module arcs to QsUtils). Direction: In.
PUBLIC int sampleOrchestrate(int a, int b);
