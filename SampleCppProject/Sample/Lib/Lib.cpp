#include "Lib.h"
#include "../Util/Util.h"

// ── Private helpers ───────────────────────────────────────────────────────────

PRIVATE int libClamp(int v, int lo, int hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

PRIVATE int libSign(int v) {
    if (v > 0) return 1;
    if (v < 0) return -1;
    return 0;
}

PRIVATE int libBound(int v, int max) {
    // Calls libClamp — private helper calling another private helper
    int lo = -max;
    return libClamp(v, lo, max);
}

// ── Public functions ──────────────────────────────────────────────────────────

PUBLIC int libAdd(int a, int b) {
    return a + b;
}

PUBLIC int libSubtract(int a, int b) {
    return a - b;
}

PUBLIC int libMultiply(int a, int b) {
    // Guard: clamp result to prevent overflow in downstream calls
    int result = a * b;
    return libBound(result, 100000);
}

PUBLIC int libAbs(int v) {
    if (v < 0) {
        return -v;
    }
    return v;
}

PUBLIC int libMax(int a, int b) {
    if (a > b) {
        return a;
    }
    return b;
}

PUBLIC int libMin(int a, int b) {
    if (a < b) {
        return a;
    }
    return b;
}

PUBLIC int libNormalize(int v, int max) {
    int clamped = libClamp(v, -max, max);     // private call
    return utilCompute(clamped, 0);           // Lib -> Util (fan-in)
}

PUBLIC int libLinearScale(int v, int from_max, int to_max) {
    // Normalize to [-1..1] range then rescale to to_max
    int sign = libSign(v);                    // private call
    int abs_v = libAbs(v);                    // public -> public call
    int normed = libNormalize(abs_v, from_max > 0 ? from_max : 1);
    int scaled = libMultiply(normed, to_max);
    return libMultiply(scaled, sign);
}
