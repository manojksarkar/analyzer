// Multi-line return type + __ONLYINT + function name (PRIVATE / __ONLYINT are not
// #defined in source; analyzer passes -DPRIVATE= -D__ONLYINT= via Clang).
typedef int UNIT;

typedef struct GG {
    int x;
} GG;

PRIVATE UNIT __ONLYINT
_SOME_FUNCTION(GG *gg) {
    (void)gg;
    return 0;
}
