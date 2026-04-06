#include "Sample.h"
#include "../Utils/SampleUtils.h"

PUBLIC int g_sampleResult = 0;
PRIVATE int g_sampleCounter = 0;

PUBLIC int sampleAdd(int a, int b) {
    return qsAdd(a, b);  // cross-module: QsCore -> QsUtils (behaviour diagram arc)
}

PUBLIC SampleStatus sampleCheck(SampleStatus s) {
    return s == SAMPLE_OK ? SAMPLE_OK : SAMPLE_ERR;
}

PUBLIC int samplePointSum(SamplePoint p) {
    return p.x + p.y;
}

PROTECTED int sampleGetCounter() {
    return g_sampleCounter;  // reads only -> direction Out
}

PUBLIC void sampleSetResult(int v) {
    g_sampleResult = v;  // writes only -> direction In
}

PRIVATE int sampleHelper(int x) {
    if (x > 0) {
        return x * 2;
    } else {
        return 0;
    }
}

PUBLIC int sampleCompute(int x) {
    int h = sampleHelper(x);            // private callee flowchart
    int n = qsNormalize(h, 100);        // cross-module: QsCore -> QsUtils
    if (n > 50) {
        return n - 50;
    }
    return n;
}

PUBLIC int sampleLoopSum(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += i;
    }
    return sum;
}

PRIVATE int sampleSwitch(int op) {
    switch (op) {
        case 1: return 10;
        case 2: return 20;
        case 3: return 30;
        default: return 0;
    }
}

PUBLIC int sampleOrchestrate(int a, int b) {
    int h = sampleHelper(a);            // private callee 1
    int s = sampleSwitch(b % 4);        // private callee 2
    int sum = qsAdd(h, s);              // cross-module: QsCore -> QsUtils
    return qsNormalize(sum, 200);       // cross-module: QsCore -> QsUtils
}
