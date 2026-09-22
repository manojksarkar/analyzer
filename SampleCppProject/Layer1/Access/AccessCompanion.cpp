#include "AccessCompanion.h"

// Out-of-line definitions: the label lives on the declaration in AccessCompanionDecl.h and
// the cursor the parser walks is here. Clang reports the access on this cursor too, so both
// methods record `public` and nothing but their callers tells them apart.

int CompanionOwner::companionFromHeader(int v) {
    return v + 3;
}

int CompanionOwner::companionFromOtherUnit(int v) {
    return v + 4;
}

// The same-unit caller of the header's inline function.
int companionEntry(int v) {
    return companionInlineUsedByCpp(v) + 5;
}
