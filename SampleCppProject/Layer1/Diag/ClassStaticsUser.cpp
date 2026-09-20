#include "ClassStatics.h"

// A SECOND translation unit writing the same member. The definition lives in another TU, so
// clang resolves this reference to the in-class DECLARATION -- and that declaration is
// recorded here as its own entry. Collapsing it onto the definition is what keeps one
// variable from becoming two model entries with the reads and writes split between them.
PUBLIC void statBumpFromOtherUnit(void) {
    StatCounters::s_publicCount += 2;
}

// Gives the two NsCounters methods a caller in ANOTHER FILE, so they reach the interface
// table and their In/Out is visible in the document. The protected member they touch stays
// out of it -- which is the whole point of the pair: the direction is published, the
// storage that decides it is not.
PUBLIC void statDriveNsCounter(void) {
    NsCounters c;
    c.bumpNs();
    c.peekNs();
    c.bumpNsPlain();
    NS::Wrapped w;
    w.bumpWrapped();
}
