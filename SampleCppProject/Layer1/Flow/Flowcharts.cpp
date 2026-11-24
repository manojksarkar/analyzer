#include "Flowcharts.h"
#include "Math/Utils.h"

PRIVATE int fnIfSimple(int x) {
    if (x > 0) {
        return x + 1;
    }
    return x;
}

PRIVATE int fnIfElse(int x) {
    if (x > 0) {
        return 1;
    } else {
        return -1;
    }
}

PRIVATE int fnNestedIfElse(int a, int b) {
    if (a > 0) {
        if (b > 0) {
            return a + b;
        } else {
            return a - b;
        }
    } else {
        if (b > 0) {
            return b - a;
        } else {
            return -(a + b);
        }
    }
}

PRIVATE int fnIfElseIf(int x) {
    if (x < 0) {
        return -1;
    } else if (x == 0) {
        return 0;
    } else if (x < 10) {
        return 1;
    } else {
        return 10;
    }
}

PRIVATE int fnSwitchSimple(int op) {
    int result = 0;
    switch (op) {
        case 1: result = 10; break;
        case 2: result = 20; break;
        case 3: result = 30; break;
        default: result = 0; break;
    }
    return result;
}

PRIVATE int fnSwitchFallthrough(int tier) {
    int bonus = 0;
    switch (tier) {
        case 3: bonus += 100;
        case 2: bonus += 50;
        case 1: bonus += 10;
        default: bonus += 1; break;
    }
    return bonus;
}

PRIVATE int fnForLoop(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        sum += i;
    }
    return sum;
}

PRIVATE int fnForBreak(int n, int stop) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        if (i == stop) break;
        sum += i;
    }
    return sum;
}

PRIVATE int fnForContinue(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        if (i % 2 == 0) continue;
        sum += i;
    }
    return sum;
}

PRIVATE int fnWhileLoop(int n) {
    int sum = 0;
    int i = 0;
    while (i < n) {
        sum += i;
        ++i;
    }
    return sum;
}

PRIVATE int fnDoWhile(int n) {
    int sum = 0;
    int i = 0;
    do {
        sum += i;
        ++i;
    } while (i < n);
    return sum;
}

PRIVATE int fnNestedFor(int rows, int cols) {
    int total = 0;
    for (int r = 0; r < rows; ++r) {
        for (int c = 0; c < cols; ++c) {
            total += r * cols + c;
        }
    }
    return total;
}

PRIVATE int fnForWithIf(int n) {
    int sum = 0;
    for (int i = 0; i < n; ++i) {
        if (i % 2 == 0) {
            sum += i * 2;
        } else {
            sum += i;
        }
    }
    return sum;
}

PRIVATE int fnWhileWithIf(int n) {
    int i = 0;
    int sum = 0;
    while (i < n) {
        if (i > n / 2) {
            sum += 1;
        } else {
            sum += 2;
        }
        ++i;
    }
    return sum;
}

PRIVATE int fnIfEarlyReturn(int x) {
    if (x < 0) return 0;
    if (x > 100) return 100;
    return x;
}

PRIVATE int fnMixedForSwitch(int n) {
    int result = 0;
    for (int i = 0; i < n; ++i) {
        switch (i % 3) {
            case 0: result += 1; break;
            case 1: result += 2; break;
            case 2: result += 3; break;
        }
    }
    return result;
}

PRIVATE int fnDeeplyNested(int a, int b, int c) {
    if (a > 0) {
        if (b > 0) {
            if (c > 0) {
                return a + b + c;
            } else {
                return a + b;
            }
        } else {
            if (c > 0) {
                return a + c;
            } else {
                return a;
            }
        }
    } else {
        if (b > 0) {
            return b + c;
        } else {
            return c;
        }
    }
}

PRIVATE int fnMultipleReturns(int x, int y) {
    if (x < 0) return -1;
    if (y < 0) return -2;
    if (x == y) return 0;
    if (x > y) return 1;
    return 2;
}

PRIVATE int fnLoopNestedIfElse(int n) {
    int s = 0;
    for (int i = 0; i < n; ++i) {
        if (i < n / 3) {
            s += 1;
        } else if (i < 2 * n / 3) {
            s += 2;
        } else {
            s += 3;
        }
    }
    return s;
}

// Calls whose result is an object, not the action itself. The label must still
// name the call as Name(), but the verb belongs to the statement — see
// "Label Policy" in engine/flowchart/README.md.

static FlowSlot_t g_flowSlot;

PRIVATE FlowSlot_t* flowSlotHandle() {
    return &g_flowSlot;
}

// fn()->field = value  — the call supplies the object being written
PRIVATE void fnCallResultFieldWrite(int slot) {
    flowSlotHandle()->timeSlot = slot;
    flowSlotHandle()->active = 0;
}

// x = fn()->field  — the call supplies the object being read
PRIVATE int fnCallResultFieldRead() {
    return flowSlotHandle()->timeSlot;
}

// p = &fn()->field  — address of a member of the returned object
PRIVATE int* fnCallResultFieldAddress() {
    int* p = &flowSlotHandle()->retryCount;
    return p;
}

// Both shapes plus a branch, so the CFG is not one straight line
PRIVATE int fnCallResultMixed(int delta) {
    int base = fnCallResultFieldRead();
    if (base < 0) {
        flowSlotHandle()->retryCount = 0;
        return 0;
    }
    flowSlotHandle()->retryCount = base + delta;
    return flowSlotHandle()->retryCount;
}

// Test: a return inside an extra { } block -- here the else of an #if whose macro is off --
// ends its branch: the Return goes to End, not on to the next statement.
PRIVATE int fnReturnInBraces(int avail, int hw) {
    int used = 0;
    if (!avail) {
#if (FLOW_FEATURE_RESET)
        if (hw) {
            used = 1;
        }
        else
#endif
        {
            return -1;
        }
    }
    used += 2;
    return used;
}

// Test: a switch on a scoped enum -- two cases share a box (one arrow, both constants),
// and a case written in braces keeps its break instead of falling into the next case.
enum class FlowMode { eREAD, eREAD_FUA, ePRE_FETCH, eIDLE };

PRIVATE int fnSwitchBracedCase(FlowMode mode) {
    int cost = 0;
    switch (mode) {
        case FlowMode::eREAD:
        case FlowMode::eREAD_FUA:
            cost = 1;
            break;
        case FlowMode::ePRE_FETCH: {
            cost = 2;
            break;
        }
        default:
            cost = 0;
            break;
    }
    return cost;
}

// Test: an empty branch -- here an else that an #if whose macro is off empties -- keeps its
// arrow: the No side goes on to the next statement.
PRIVATE int fnEmptyElse(int x) {
    int level = 0;
    if (x > 0) {
        level = 1;
    } else {
#if (FLOW_FEATURE_TRACE)
        level = -1;
#endif
    }
    level += x;
    return level;
}

// Test: an empty then -- an #if whose macro is off empties it -- keeps its arrow: the Yes
// side goes on to the next statement.
PRIVATE int fnEmptyThen(int x) {
    int level = 0;
    if (x > 10) {
#if (FLOW_FEATURE_TRACE)
        level = -1;
#endif
    } else {
        level = 1;
    }
    level += x;
    return level;
}

// Test: a loop with an empty body waits on its condition: the Yes arrow loops on the head.
PRIVATE int fnWaitReady(volatile int *ready) {
    while (!*ready) {
    }
    return *ready;
}

// Test: a do-while with an empty body is still entered, and its Yes arrow loops on the head.
PRIVATE int fnWaitIdle(volatile int *busy) {
    do {
    } while (*busy);
    return *busy;
}

// Test: a for loop with an empty body counts on its condition: the Yes arrow loops on the head.
PRIVATE int fnTextLength(const char *buf) {
    int len;
    for (len = 0; buf[len] != 0; ++len) {
    }
    return len;
}

// Test: a continue inside a switch case goes back to the loop around the switch.
PRIVATE int fnSwitchContinue(int n) {
    int hits = 0;
    for (int i = 0; i < n; ++i) {
        switch (i % 3) {
            case 0:
                continue;
            case 1:
                hits += 1;
                break;
            default:
                hits += 2;
                break;
        }
        hits += 10;
    }
    return hits;
}

// Test: labels keep the code's values, and boxes with different code keep different labels
// (review SWE3-013, -014): the first diamond names 3 and FLOW_RETRY_MAX, the two speed boxes
// stay "... 10" and "... 2". Without the LLM every label is its code, so only an LLM run shows it.
#define FLOW_RETRY_MAX 5
PRIVATE int fnRetrySpeed(int retry, int fast) {
    int speed = 0;
    if (retry > 3 && retry < FLOW_RETRY_MAX) {
        return -1;
    }
    if (fast) {
        speed = 10;
    } else {
        speed = 2;
    }
    return speed;
}

PUBLIC int runFlowTests() {
    int total = 0;
    total += fnIfSimple(5);
    total += fnIfElse(-3);
    total += fnNestedIfElse(2, 3);
    total += fnIfElseIf(5);
    total += fnSwitchSimple(2);
    total += fnSwitchFallthrough(2);
    total += fnForLoop(10);
    total += fnForBreak(20, 5);
    total += fnForContinue(10);
    total += fnWhileLoop(5);
    total += fnDoWhile(5);
    total += fnNestedFor(3, 4);
    total += fnForWithIf(8);
    total += fnWhileWithIf(6);
    total += fnIfEarlyReturn(50);
    total += fnMixedForSwitch(6);
    total += fnDeeplyNested(1, 1, 1);
    total += fnMultipleReturns(3, 2);
    total += fnLoopNestedIfElse(9);
    fnCallResultFieldWrite(7);
    total += fnCallResultFieldRead();
    total += *fnCallResultFieldAddress();
    total += fnCallResultMixed(3);
    total += fnReturnInBraces(0, 1);
    total += fnSwitchBracedCase(FlowMode::ePRE_FETCH);
    total += fnEmptyElse(-2);
    total += fnEmptyThen(3);
    volatile int ready = 1;
    total += fnWaitReady(&ready);
    volatile int busy = 0;
    total += fnWaitIdle(&busy);
    total += fnTextLength("flow");
    total += fnSwitchContinue(6);
    total += fnRetrySpeed(4, 1);
    return total;
}
