#pragma once

// Layer2's Lib — the TWIN of Layer1/Sample/Lib/Lib.h.
//
// Component name ("Lib"), unit name ("Lib"), function names and global names are
// all IDENTICAL to Layer1's on purpose. This is the fixture for layer-qualified
// identity: with bare names these two collapsed into one component holding both
// layers' files, one unit, and one set of function keys. The ids are
// `Layer2.Lib|Lib|libAdd|int,int` vs `Layer1.Lib|Lib|libAdd|int,int` now.
//
// The BEHAVIOUR is deliberately different (saturating, byte-oriented) so a
// reviewer reading a generated document can tell instantly which layer it came
// from. Self-contained: it does NOT include Layer1's Types, because a cross-layer
// include would defeat the point of the two layers being separate parse scopes.

// Lib-local enum — same NAME as Layer1's Status, different members.
enum Status { STATUS_OK = 0, STATUS_ERR = 1, STATUS_SATURATED = 2 };

#define LIB2_MAX_BYTE 255
#define LIB2_MIN_BYTE 0

// Globals — same names as Layer1's Lib globals.
PUBLIC extern int g_libTotal;      // written by libAdd      -> direction In
PRIVATE extern int g_libCalls;     // read by libCallCount   -> direction Out

// ── PUBLIC functions ─────────────────────────────────────────────────────────

PUBLIC int libAdd(int a, int b);              // saturating add, not Layer1's plain add
PUBLIC int libNormalize(int v, int span);     // clamps into 0..255, not a modulo
PUBLIC int libMultiply(int a, int b);         // saturating multiply
PUBLIC Status libClassify(int v);             // returns the local Status enum

// ── PROTECTED ────────────────────────────────────────────────────────────────

PROTECTED int libCallCount();                 // reads g_libCalls -> direction Out

// ── PRIVATE ──────────────────────────────────────────────────────────────────

PRIVATE int libSaturate(int v);               // shared clamp helper
