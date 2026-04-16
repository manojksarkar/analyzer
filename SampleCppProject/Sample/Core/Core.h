#pragma once

#include "../../Types/Types.h"
#include "../../Types/PointRect.h"

// Core-local enum — tests enum params in interface table.
enum Mode { MODE_FAST = 0, MODE_SAFE = 1 };

// Globals
PUBLIC extern int g_result;        // written by coreSetResult -> direction In
PRIVATE extern int g_count;        // read by coreGetCount  -> direction Out; excluded from interface table

// PUBLIC functions
PUBLIC int coreAdd(int a, int b);          // calls libAdd -> behaviour diagram arc
PUBLIC int coreCompute(int x);             // if/else + private callee coreHelper -> flowchart
PUBLIC int coreLoopSum(int n);             // for loop -> flowchart
PUBLIC Status coreCheck(Status s);         // enum param -> interface table type
PUBLIC int coreSumPoint(Point p);          // struct param -> interface table type
PUBLIC void coreSetResult(int v);          // writes g_result -> direction In
PUBLIC int coreProcess(int a, int b);      // calls libNormalize -> behaviour diagram arc
PUBLIC int coreOrchestrate(int a, int b);  // hub: calls libAdd + libNormalize + utilCompute + utilScale -> fan-out behaviour diagram
PUBLIC Mode coreSetMode(Mode m);           // Mode enum param -> interface table type

// PROTECTED function
PROTECTED int coreGetCount();              // reads g_count only -> direction Out

// PRIVATE functions (excluded from interface table and behaviour diagram)
PRIVATE int coreHelper(int x);             // if/else; callee of coreCompute -> appears in flowchart
PRIVATE int coreSwitch(int op);            // switch/case -> appears in flowchart
