// Forward declaration only in this TU (no body): should appear in functions.json
// with declarationOnly, not as a global. No "typedef void VOID" here — the analyzer
// passes -DVOID=void (see src/parser.py); real projects may use a typedef instead.
PROTECTED VOID
_SOME_OTHER_FUNCTION(VOID);
