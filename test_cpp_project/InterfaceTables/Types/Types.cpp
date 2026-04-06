#include "Types.h"
#include "../../UnitDiagrams/Nested/Inner/Helper.h"

// Test macros for enum-related defines
#define STATUS_OK_CODE  0
#define STATUS_ERR_CODE 1

PUBLIC Status checkStatus(Status s) {
    return s == STATUS_OK ? STATUS_OK : STATUS_ERR;
}

PUBLIC Color nextColor(Color c) {
    if (c == RED) return GREEN;
    if (c == GREEN) return BLUE;
    return RED;
}

PROTECTED Mode_t setMode(Mode_t m) {
    return m;
}

PUBLIC Status getDefaultStatus() {
    return STATUS_OK;
}

PUBLIC Color getDefaultColor() {
    return RED;
}

PRIVATE int enumWithHelper(int x) {
    return nestedHelper(x);  // cross-module: tests/enum -> outer
}
