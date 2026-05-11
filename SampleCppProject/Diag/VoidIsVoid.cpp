// PRIVATE is not #defined anywhere; VOID is supplied as void via -DVOID=void (parser).
typedef int UNIT;

PRIVATE UNIT
_ok_when_void_is_void(VOID) {
    return 0;
}
