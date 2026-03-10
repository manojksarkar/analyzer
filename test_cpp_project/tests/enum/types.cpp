#include "types.h"
#include "../../outer/inner/helper.h"

// Test macros for enum-related defines
#define STATUS_OK_CODE  0
#define STATUS_ERR_CODE 1

Status checkStatus(Status s) {
    return s == STATUS_OK ? STATUS_OK : STATUS_ERR;
}

Color nextColor(Color c) {
    if (c == RED) return GREEN;
    if (c == GREEN) return BLUE;
    return RED;
}

Mode_t setMode(Mode_t m) {
    return m;
}

Status getDefaultStatus() {
    return STATUS_OK;
}

Color getDefaultColor() {
    return RED;
}

int enumWithHelper(int x) {
    return nestedHelper(x);  // cross-module: tests/enum -> outer
}
