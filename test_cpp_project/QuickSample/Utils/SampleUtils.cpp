#include "SampleUtils.h"

PUBLIC int qsAdd(int a, int b) {
    return a + b;
}

PRIVATE int qsClamp(int value, int max) {
    if (value < 0) return 0;
    if (value > max) return max;
    return value;
}

PUBLIC int qsNormalize(int value, int max) {
    int clamped = qsClamp(value, max);  // private callee
    if (max == 0) return 0;
    return (clamped * 100) / max;
}
