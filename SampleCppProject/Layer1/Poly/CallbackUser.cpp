#include "Callbacks.h"

// Test: the functions handed to Callbacks.cpp. Nothing calls them by name; Callbacks.cpp
// calls them through a pointer, so they are this unit's interface, called by Callbacks.

static int cbUserOnRead(int x) {
    return x + 1;
}

static int cbUserDouble(int x) {
    return x * 2;
}

// Stored in CbOps's fields, in order: onRead, add.
static const CbOps s_userOps = { cbUserOnRead, cbUserDouble };

PUBLIC int cbUserRun(int x) {
    cbRegister(cbUserOnRead);
    cbRegisterOps(&s_userOps);
    return cbFire(x) + cbApply(&s_userOps, x);
}
