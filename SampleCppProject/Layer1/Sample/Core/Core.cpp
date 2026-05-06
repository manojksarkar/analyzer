#include "Core.h"
#include "../Lib/Lib.h"
#include "../Util/Util.h"

PUBLIC int g_result = 0;
PRIVATE int g_count = 0;

// ── Private helpers ───────────────────────────────────────────────────────────

PRIVATE int coreTransform(int v) {
    // Deepest node in the private call chain — simple arithmetic
    if (v < 0) {
        return -v * 2;
    }
    return v * 2 + 1;
}

PRIVATE int coreValidate(int v) {
    // Middle of the private chain: guards then delegates to coreTransform
    if (v == 0) {
        return 0;
    }
    if (v < -100 || v > 100) {
        return coreTransform(100);   // clamp extreme values
    }
    return coreTransform(v);
}

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

// ── Public / Protected functions ─────────────────────────────────────────────

PUBLIC int coreAdd(int a, int b) {
    return libAdd(a, b);   // Core -> Lib
}

PUBLIC int coreCompute(int x) {
    int h = coreHelper(x);     // private callee
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
    return libNormalize(a, b);  // Core -> Lib
}

PUBLIC int coreOrchestrate(int a, int b) {
    int sum   = libAdd(a, b);            // Core -> Lib
    int norm  = libNormalize(sum, 100);  // Core -> Lib
    int comp  = utilCompute(a, b);       // Core -> Util
    int scale = utilScale(norm, 2);      // Core -> Util
    return sum + norm + comp + scale;
}

PUBLIC Mode coreSetMode(Mode m) {
    return m;
}

PUBLIC int coreWhileCount(int limit) {
    // While loop: increment until limit, with safety break
    int count = 0;
    while (count < limit) {
        count++;
        if (count > 1000) {
            break;
        }
    }
    return count;
}

PUBLIC int coreNestedBranch(int a, int b) {
    // Nested if/else: 4 distinct paths
    if (a > 0) {
        if (b > 0) {
            return libAdd(a, b);
        } else {
            return utilCompute(a, -b);
        }
    } else {
        if (b > 0) {
            return libNormalize(b, a < -100 ? 100 : -a);
        } else {
            return 0;
        }
    }
}

PUBLIC int coreEarlyReturn(int x) {
    // Guard clauses with multiple early returns
    if (x < 0) {
        return -1;
    }
    if (x == 0) {
        return 0;
    }
    if (x > 10000) {
        return coreValidate(10000);
    }
    return coreValidate(x);
}

PUBLIC int corePipeline(int v) {
    // Deep call chain: public -> private validate -> private transform -> cross-module
    int validated  = coreValidate(v);
    int normalized = libNormalize(validated, 200);
    int scaled     = utilScale(normalized, 3);
    return scaled;
}

PUBLIC int coreDoWhileClamp(int v, int limit) {
    // Do-while: always executes at least once, iterates until stable
    int result = v;
    do {
        result = libNormalize(result, limit);
        limit  = limit / 2;
    } while (limit > 1 && result > limit);
    return result;
}

PUBLIC int coreMultiCallChain(int a, int b, int c) {
    // Sequential cross-module calls to Lib and Util
    int sum      = libAdd(a, b);
    int product  = libMultiply(sum, c);
    int computed = utilCompute(product, b);
    int scaled   = utilScale(computed, 2);
    int chained  = utilChain(scaled);
    return chained;
}

PROTECTED int coreGetCount() {
    return g_count;  // reads global only -> direction Out
}
