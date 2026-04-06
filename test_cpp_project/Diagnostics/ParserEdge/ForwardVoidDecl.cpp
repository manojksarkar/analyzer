// Module: diag_parser  |  Group: diagnostics
// Edge case: declarationOnly — forward declaration with no body. Parser stores
// the entry with declarationOnly=true; it should NOT appear as a global variable.
// Also tests VOID macro (supplied as -DVOID=void by analyzer, not defined here).
//
// Forward declaration only in this TU (no body): should appear in functions.json
// with declarationOnly, not as a global. No "typedef void VOID" here — the analyzer
// passes -DVOID=void (see src/parser.py); real projects may use a typedef instead.
PROTECTED VOID
_SOME_OTHER_FUNCTION(VOID);
