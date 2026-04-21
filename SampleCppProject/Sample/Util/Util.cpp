#include "Util.h"

PUBLIC int g_utilBase = 0;

// ── Private helpers ───────────────────────────────────────────────────────────

PRIVATE int utilClip(int v, int lo, int hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

PRIVATE int utilDouble(int v) {
    return v * 2;
}

PRIVATE int utilHalve(int v) {
    if (v == 0) return 0;
    return v / 2;
}

// ── Public functions ──────────────────────────────────────────────────────────

PUBLIC int utilCompute(int a, int b) {
    // Reads g_utilBase -> direction Out
    return utilClip(a + b + g_utilBase, -1000, 1000);
}

PUBLIC int utilScale(int v, int factor) {
    if (factor == 0) return 0;
    return utilClip(v * factor, -10000, 10000);
}

PUBLIC int utilAbs(int v) {
    if (v < 0) {
        return -v;
    }
    return v;
}

PUBLIC int utilClamp(int v, int lo, int hi) {
    // Public wrapper that delegates to private utilClip
    return utilClip(v, lo, hi);
}

PUBLIC int utilNorm(int v, int max) {
    // Normalize v into [-max, max] then apply compute
    int clipped = utilClip(v, -max, max);
    return utilCompute(clipped, 0);
}

PUBLIC int utilBlend(int a, int b, int w) {
    // Weighted blend: result = a*(100-w)/100 + b*w/100, clamped
    int wa = utilHalve(100 - w);   // private call
    int wb = utilHalve(w);         // private call
    int blend = a * wa + b * wb;
    return utilClamp(blend, -10000, 10000);
}

PUBLIC int utilLoopAccum(int n) {
    // For loop — accumulates sum of utilDouble of each index
    int total = 0;
    for (int i = 0; i < n; ++i) {
        total += utilDouble(i);   // private call inside loop
    }
    return utilClip(total, -100000, 100000);
}

PUBLIC int utilChain(int v) {
    // Chain of public calls — tests fan-out in flowchart
    int abs_v  = utilAbs(v);
    int normed = utilNorm(abs_v, 500);
    int scaled = utilScale(normed, 3);
    return scaled;
}
