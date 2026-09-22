#pragma once

#include "AccessCompanionDecl.h"

// h2 of the companion-unit fixture. This header and AccessCompanion.cpp are ONE unit --
// make_unit_key strips the extension -- so a call that crosses between them crosses no
// boundary the interface table recognises.

// Calls CompanionOwner::companionFromHeader, which is defined in this unit's .cpp. That
// call is the only thing reaching that method, and it must not publish it.
// This function itself is called from AccessCompanionUser.cpp, another unit, so it IS
// published: a header-defined function is published on the same terms as any other.
inline int companionHeaderInline(int v) {
    CompanionOwner owner;
    return owner.companionFromHeader(v) + 1;
}

// The mirror image: defined in the header, called only from this unit's .cpp. Same unit,
// different file, so it stays buried too. `DbSession::backoffMs` in AccessVisibility.h is
// this shape already, but it is `protected:` and so never reaches the caller rule -- this
// cell is the unmarked one, where the caller rule is all there is.
inline int companionInlineUsedByCpp(int v) {
    return v + 2;
}

// Defined in AccessCompanion.cpp; declared here so another unit can reach it.
int companionEntry(int v);
