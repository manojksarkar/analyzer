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
