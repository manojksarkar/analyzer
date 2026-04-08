#include "Lib.h"
#include "../Util/Util.h"

PRIVATE int libClamp(int v, int max) {
    if (v < 0) return 0;
    if (v > max) return max;
    return v;
}

PUBLIC int libAdd(int a, int b) {
    return a + b;
}

PUBLIC int libNormalize(int v, int max) {
    int clamped = libClamp(v, max);
    return utilCompute(clamped, 0);  // Lib -> Util (fan-in: both Core and Lib call utilCompute)
}
