// Module: diag_parser  |  Group: diagnostics
// Edge case: multi-line declaration with __OVLYINIT qualifier between return type
// and function name. _detect_visibility() must scan ≥3 lines back to find PRIVATE.
//
// Multi-line return type + __OVLYINIT + function name (PRIVATE / __OVLYINIT are not
// #defined in source; analyzer passes -DPRIVATE= -D__OVLYINIT= via Clang).
typedef int UNIT;

typedef struct GG {
    int x;
} GG;

PRIVATE UNIT __OVLYINIT
_SOME_FUNCTION(GG *gg) {
    (void)gg;
    return 0;
}
