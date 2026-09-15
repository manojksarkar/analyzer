#include "ClassStatics.h"

// A SECOND translation unit writing the same member. The definition lives in another TU, so
// clang resolves this reference to the in-class DECLARATION -- and that declaration is
// recorded here as its own entry. Collapsing it onto the definition is what keeps one
// variable from becoming two model entries with the reads and writes split between them.
PUBLIC void statBumpFromOtherUnit(void) {
    StatCounters::s_publicCount += 2;
}
