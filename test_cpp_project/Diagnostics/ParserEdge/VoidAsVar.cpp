// Module: diag_parser  |  Group: diagnostics
// Edge case: syntheticFromVarDecl — Clang mis-parses UNIT _FUNC(voidArg) as a
// VAR_DECL with initializer; parser detects and re-classifies as a function.
//
// PRIVATE is not #defined anywhere in this project; the analyzer supplies
// -DPRIVATE= (and PROTECTED/PUBLIC) on the Clang command line (see src/parser.py).
// When a variable name (not the void type) appears in parens, Clang may parse
//   UNIT _SOME_FUNCTION(voidArg)
// as a VAR_DECL with initializer (voidArg). The parser also records this shape as a
// function (syntheticFromVarDecl) so it appears in functions.json, not only globals.
// Identifier is not "VOID" because the analyzer passes -DVOID=void globally.
typedef int UNIT;

int voidArg = 1;

PRIVATE UNIT
_SOME_FUNCTION(voidArg);
