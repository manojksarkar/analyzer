#pragma once

#include "../../Types/Types.h"
#include "../../Types/PointRect.h"

// Core-local enum — tests enum params in interface table.
enum Mode { MODE_FAST = 0, MODE_SAFE = 1 };

// Globals
PUBLIC extern int g_result;        // written by coreSetResult -> direction In
PRIVATE extern int g_count;        // read by coreGetCount  -> direction Out; excluded from interface table

// ── PUBLIC functions ──────────────────────────────────────────────────────────

PUBLIC int coreAdd(int a, int b);          // calls libAdd -> cross-module call
PUBLIC int coreCompute(int x);             // if/else + private callee coreHelper
PUBLIC int coreLoopSum(int n);             // for loop accumulator
PUBLIC Status coreCheck(Status s);         // enum param -> interface table type
PUBLIC int coreSumPoint(Point p);          // struct param -> interface table type
PUBLIC void coreSetResult(int v);          // writes g_result -> direction In
PUBLIC int coreProcess(int a, int b);      // calls libNormalize -> cross-module call
PUBLIC int coreOrchestrate(int a, int b);  // hub: calls libAdd + libNormalize + utilCompute + utilScale -> fan-out
PUBLIC Mode coreSetMode(Mode m);           // Mode enum param -> interface table type

// Flowchart patterns
PUBLIC int coreWhileCount(int limit);                // while loop
PUBLIC int coreNestedBranch(int a, int b);           // nested if/else with 4 paths
PUBLIC int coreEarlyReturn(int x);                   // multiple return points (guards)
PUBLIC int corePipeline(int v);                      // deep call chain: validate->transform->normalize->scale
PUBLIC int coreDoWhileClamp(int v, int limit);       // do-while loop
PUBLIC int coreMultiCallChain(int a, int b, int c);  // calls libAdd, libMultiply, utilCompute in sequence

// ── PROTECTED function ────────────────────────────────────────────────────────

PROTECTED int coreGetCount();              // reads g_count only -> direction Out

// ── PRIVATE functions (excluded from interface table and behaviour diagram) ───

PRIVATE int coreHelper(int x);            // if/else; callee of coreCompute
PRIVATE int coreSwitch(int op);           // switch/case
PRIVATE int coreValidate(int v);          // called by corePipeline; calls coreTransform
PRIVATE int coreTransform(int v);         // deepest private in corePipeline chain
