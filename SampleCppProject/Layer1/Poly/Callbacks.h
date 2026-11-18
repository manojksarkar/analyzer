#pragma once

// Test: calls through a function pointer (review SWE3-V5-02). A function is put into a
// field or a variable in one place and called through it in another; the call reaches
// every function stored there. CallbackUser.cpp registers them, Callbacks.cpp calls them.

typedef int (*CbFn)(int);

// `add` is also the name of a Math function: a call through this field must reach what the
// field holds, never Math's add.
struct CbOps {
    CbFn onRead;
    CbFn add;
};

PUBLIC void cbRegister(CbFn fn);
PUBLIC int cbFire(int x);
PUBLIC int cbApply(const CbOps* ops, int x);
PUBLIC int cbUserRun(int x);

// Test: a dynamic behaviour that exists only through a pointer (review SWE3-V5-01). App calls
// cbDispatch from another component; cbDispatch reaches CallbackUser (this component's other
// unit) only through `s_ops->onRead`. Without the pointer link it calls nothing, so it got no
// dynamic behaviour entry (SWE3-DB-01); with it, the entry draws the call into CallbackUser.
PUBLIC void cbRegisterOps(const CbOps* ops);
PUBLIC int cbDispatch(int x);
