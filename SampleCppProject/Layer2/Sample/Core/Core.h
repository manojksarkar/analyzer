#pragma once

#include "../Lib/Lib.h"

// Layer2's Core — the TWIN of Layer1/Sample/Core/Core.h.
//
// Component name ("Sample Core"), unit name ("Core"), the group that owns it
// ("My Sample"), the function names, the global names and even the Mode enum are
// IDENTICAL to Layer1's. That is the whole point: with bare names these two
// produced the same `Sample-Core|Core` unit key and merged into one unit carrying
// both layers' functions. Qualified, they are `Layer1.Sample-Core|Core` and
// `Layer2.Sample-Core|Core`.
//
// Behaviour is deliberately different (byte/saturating rather than arithmetic) so
// a reviewer can tell which layer a generated document describes.

// Core-local enum — same NAME as Layer1's Mode, different members.
enum Mode { MODE_FAST = 0, MODE_SAFE = 1, MODE_BURST = 2 };

// Globals — same names as Layer1's Core globals.
PUBLIC extern int g_result;        // written by coreSetResult -> direction In
PRIVATE extern int g_count;        // read by coreGetCount     -> direction Out

// ── PUBLIC functions ─────────────────────────────────────────────────────────

PUBLIC int coreAdd(int a, int b);          // calls Layer2's libAdd, not Layer1's
PUBLIC int coreCompute(int x);             // if/else + private callee coreHelper
PUBLIC void coreSetResult(int v);          // writes g_result -> direction In
PUBLIC int coreProcess(int a, int b);      // calls libNormalize
PUBLIC Mode coreSetMode(Mode m);           // Mode enum param
PUBLIC Status coreClassify(int v);         // returns Layer2's Lib Status enum
PUBLIC int coreBurstFill(int n);           // while loop, Layer2-only

// ── PROTECTED ────────────────────────────────────────────────────────────────

PROTECTED int coreGetCount();              // reads g_count only -> direction Out

// ── PRIVATE ──────────────────────────────────────────────────────────────────

PRIVATE int coreHelper(int x);             // callee of coreCompute
