#include "Callbacks.h"

// Test: the registered function is kept in a variable, then called through it.
static CbFn s_handler = 0;

PUBLIC void cbRegister(CbFn fn) {
    s_handler = fn;
}

// Reaches whatever cbRegister was given (CallbackUser's cbUserOnRead).
PUBLIC int cbFire(int x) {
    if (s_handler) {
        return s_handler(x);
    }
    return 0;
}

// Reaches what the two fields hold (cbUserOnRead, cbUserDouble) -- not Math's add.
PUBLIC int cbApply(const CbOps* ops, int x) {
    return ops->onRead(x) + ops->add(x);
}

// Test: the table CallbackUser registers, called through `->` (see Callbacks.h).
static const CbOps* s_ops = 0;

PUBLIC void cbRegisterOps(const CbOps* ops) {
    s_ops = ops;
}

PUBLIC int cbDispatch(int x) {
    if (!s_ops) {
        return 0;
    }
    return s_ops->onRead(x);
}
