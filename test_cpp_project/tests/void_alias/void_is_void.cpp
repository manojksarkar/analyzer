// PRIVATE is not #defined anywhere in this project; see void_as_var.cpp comment.
// Contrast: VOID expands to void — same layout, but this is a real function.
#define VOID void
typedef int UNIT;

PRIVATE UNIT
_ok_when_void_is_void(VOID) {
    return 0;
}
