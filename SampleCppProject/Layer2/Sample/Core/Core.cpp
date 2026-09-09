#include "Core.h"

PUBLIC int g_result = 0;
PRIVATE int g_count = 0;

// ── Private ──────────────────────────────────────────────────────────────────

PRIVATE int coreHelper(int x) {
    // Layer1's coreHelper returns x + 1 for positives; this one doubles and
    // saturates through Layer2's Lib. Same name, different unit, different answer.
    if (x > 0) {
        return libSaturate(x * 2);
    }
    return 0;
}

// ── Public / Protected ───────────────────────────────────────────────────────

PUBLIC int coreAdd(int a, int b) {
    g_count++;
    return libAdd(a, b);          // Layer2 Core -> Layer2 Lib
}

PUBLIC int coreCompute(int x) {
    int h = coreHelper(x);        // private callee
    if (h > 0) {
        return libNormalize(h, LIB2_MAX_BYTE);
    }
    return 0;
}

PUBLIC void coreSetResult(int v) {
    g_result = libSaturate(v);    // writes global -> direction In
}

PUBLIC int coreProcess(int a, int b) {
    g_count++;
    return libNormalize(a, b);    // Layer2 Core -> Layer2 Lib
}

PUBLIC Mode coreSetMode(Mode m) {
    if (m == MODE_BURST) {
        return MODE_SAFE;         // burst is downgraded here, unlike Layer1
    }
    return m;
}

PUBLIC Status coreClassify(int v) {
    return libClassify(v);        // returns Layer2's Lib Status
}

PUBLIC int coreBurstFill(int n) {
    // While loop with a saturating accumulator — no Layer1 counterpart.
    int filled = 0;
    while (filled < n) {
        filled = libAdd(filled, 8);
        if (filled >= LIB2_MAX_BYTE) {
            break;
        }
    }
    return filled;
}

PROTECTED int coreGetCount() {
    return g_count;               // reads global only -> direction Out
}
