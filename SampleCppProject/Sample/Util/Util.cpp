#include "Util.h"

PUBLIC int g_utilBase = 0;

PRIVATE int utilClip(int v, int lo, int hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

PUBLIC int utilCompute(int a, int b) {
    return utilClip(a + b + g_utilBase, -1000, 1000);  // reads g_utilBase -> direction Out
}

PUBLIC int utilScale(int v, int factor) {
    if (factor == 0) return 0;
    return utilClip(v * factor, -10000, 10000);
}
