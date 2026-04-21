#include "Core.h"
#include "../Lib/Lib.h"
#include "../Util/Util.h"

PUBLIC int g_result = 0;
PRIVATE int g_count = 0;

// Private helpers — visible in flowchart, excluded from interface table and behaviour diagram.

PRIVATE int coreHelper(int x) {
    if (x > 0) {
        return x + 1;
    } else {
        return 0;
    }
}

PRIVATE int coreSwitch(int op) {
    int result = 0;
    switch (op) {
        case 1: result = 10; break;
        case 2: result = 20; break;
        case 3: result = 30; break;
        default: result = -1; break;
    }
    return result;
}

// Public / Protected functions.

PUBLIC int coreAdd(int a, int b) {
    return libAdd(a, b);   // cross-module: Core -> Lib (behaviour diagram arc)
}

PUBLIC int coreCompute(int x) {
    int h = coreHelper(x);  // private callee -> appears in flowchart as private callee chart
    if (h > 0) {
        return h * 2;
    } else {
        return coreSwitch(x % 4);
    }
}

PUBLIC int coreLoopSum(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += i;
    }
    return sum;
}

PUBLIC Status coreCheck(Status s) {
    return s == STATUS_OK ? STATUS_OK : STATUS_ERR;
}

PUBLIC int coreSumPoint(Point p) {
    return p.x + p.y;
}

PUBLIC void coreSetResult(int v) {
    g_result = v;   // writes global -> direction In
}

PUBLIC int coreProcess(int a, int b) {
    return libNormalize(a, b);  // cross-module: Core -> Lib (behaviour diagram arc)
}

PROTECTED int coreGetCount() {
    return g_count;  // reads global only -> direction Out
}

PUBLIC int coreOrchestrate(int a, int b) {
    // Hub function: fan-out to Lib and Util -> rich behaviour diagram
    int sum   = libAdd(a, b);           // Core -> Lib
    int norm  = libNormalize(sum, 100); // Core -> Lib
    int comp  = utilCompute(a, b);      // Core -> Util
    int scale = utilScale(norm, 2);     // Core -> Util
    return sum + norm + comp + scale;
}

PUBLIC Mode coreSetMode(Mode m) {
    return m;   // Mode enum param and return -> richer interface table types
}
