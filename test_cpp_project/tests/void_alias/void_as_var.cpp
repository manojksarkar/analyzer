// PRIVATE is not #defined anywhere in this project; the analyzer supplies
// -DPRIVATE= (and PROTECTED/PUBLIC) on the Clang command line (see src/parser.py).
// When VOID names a variable (not the void type), Clang parses
//   UNIT _SOME_FUNCTION(VOID)
// as a VAR_DECL with initializer (VOID). The parser also records this shape as a
// function (syntheticFromVarDecl) so it appears in functions.json, not only globals.
typedef int UNIT;

int VOID = 1;

PRIVATE UNIT
_SOME_FUNCTION(VOID);
