// Module: diag_parser  |  Group: diagnostics
// Edge case: preprocessor #if with SOME_THING=1 (THEN branch taken).
// Verifies that the parser correctly resolves _SOME_FUNCTION_IF_BRANCH(GG *gg)
// when the #if evaluates to true — complementary to preproc_if_function.cpp.
//
// Same layout as preproc_if_function.cpp, but SOME_THING is defined so the #if
// branch is taken (_SOME_FUNCTION(GG *gg)). Real projects often get this via
// -DSOME_THING=1 in the build instead of a #define in the file.
#define SOME_THING 1

typedef int UNIT;

typedef struct GG {
    int x;
} GG;

PRIVATE UNIT
#if (SOME_THING)
_SOME_FUNCTION_IF_BRANCH(GG *gg)
#else
_SOME_FUNCTION_IF_BRANCH()
#endif
{
    (void)gg;
    return 0;
}
