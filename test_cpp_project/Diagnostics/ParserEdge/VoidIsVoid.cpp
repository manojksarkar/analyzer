// Module: diag_parser  |  Group: diagnostics
// Edge case: VOID used as formal parameter type (i.e. f(VOID) ≡ f(void)).
// The analyzer passes -DVOID=void so Clang sees a proper void parameter list.
// Distinguishes from the syntheticFromVarDecl case in void_as_var.cpp.
//
// PRIVATE is not #defined anywhere; VOID is supplied as void via -DVOID=void (parser).
typedef int UNIT;

PRIVATE UNIT
_ok_when_void_is_void(VOID) {
    return 0;
}
