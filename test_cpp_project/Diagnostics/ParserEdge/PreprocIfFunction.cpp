// Module: diag_parser  |  Group: diagnostics
// Edge case: preprocessor #if splits the function name — Clang resolves the
// ELSE branch (SOME_THING not defined → 0) and sees _SOME_FUNCTION().
// Parser must handle the resulting AST node correctly.
//
// Return type and function name are split by preprocessor; only one branch is
// visible after preprocessing. If SOME_THING is not defined, #if(SOME_THING) is 0
// and the #else branch is used (see C/C++ #if rules).
typedef int UNIT;

typedef struct GG {
    int x;
} GG;

PRIVATE UNIT
#if (SOME_THING)
_SOME_FUNCTION(GG *gg)
#else
_SOME_FUNCTION()
#endif
{
    return 0;
}
