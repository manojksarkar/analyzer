#include "Lib.h"

PUBLIC int g_libTotal = 0;
PRIVATE int g_libCalls = 0;

// ── Private ──────────────────────────────────────────────────────────────────

PRIVATE int libSaturate(int v) {
    // Clamp into the byte range rather than wrapping — Layer1's Lib does neither.
    if (v > LIB2_MAX_BYTE) {
        return LIB2_MAX_BYTE;
    }
    if (v < LIB2_MIN_BYTE) {
        return LIB2_MIN_BYTE;
    }
    return v;
}

// ── Public / Protected ───────────────────────────────────────────────────────

PUBLIC int libAdd(int a, int b) {
    // Saturating add. Layer1's libAdd is a plain a + b.
    g_libCalls++;
    int sum = libSaturate(a + b);
    g_libTotal = sum;          // writes global -> direction In
    return sum;
}

PUBLIC int libMultiply(int a, int b) {
    g_libCalls++;
    return libSaturate(a * b);
}

PUBLIC int libNormalize(int v, int span) {
    // Clamp into 0..span, guarding a zero span. Layer1's libNormalize takes a modulo.
    g_libCalls++;
    if (span <= 0) {
        return 0;
    }
    if (v > span) {
        return span;
    }
    if (v < 0) {
        return 0;
    }
    return v;
}

PUBLIC Status libClassify(int v) {
    if (v >= LIB2_MAX_BYTE) {
        return STATUS_SATURATED;
    }
    if (v < LIB2_MIN_BYTE) {
        return STATUS_ERR;
    }
    return STATUS_OK;
}

PROTECTED int libCallCount() {
    return g_libCalls;         // reads global only -> direction Out
}
