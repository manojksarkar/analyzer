// MissingHeaderSwitch.cpp — a header this machine does not have.
//
// Firmware is compiled with armclang and parsed here with libclang, so a toolchain header or a
// project header outside the include paths may not be reachable. The parse goes on past it, and
// a statement that uses one of its names stays in the tree as text. A `case` does not: clang
// makes no case statement for a constant it cannot resolve and leaves the case's statements
// loose in the switch body, so the branch used to be missing from the flowchart and from the
// test steps. Both cases below must be there.
#include "NotOnThisMachine.h"

int g_missingMode;

PUBLIC int missingHeaderSwitch(int mode) {
    switch (mode) {
    case MODE_FROM_MISSING_HEADER_A:
        g_missingMode = 1;
        break;
    case MODE_FROM_MISSING_HEADER_B:
        g_missingMode = 2;
        break;
    default:
        g_missingMode = 0;
        break;
    }
    return g_missingMode;
}
