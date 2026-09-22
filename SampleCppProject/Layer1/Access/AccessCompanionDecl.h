#pragma once

// h1 of the companion-unit fixture: a class DECLARED here, DEFINED in AccessCompanion.cpp,
// and reached from AccessCompanion.h. Three files, and the question the model has to answer
// is which of them count as "somewhere else".
//
// Nothing here carries a PRIVATE/PUBLIC macro on purpose. The C++ access label is the only
// marking, so `public:` records `public` and the call graph alone decides publication --
// which is what puts the whole weight of these cells on the caller rule.
//
// This header has no same-name source file, so it is never a unit of its own; the members
// below belong to the unit their DEFINITION sits in, which is AccessCompanion.

class CompanionOwner {
public:
    // Called ONLY from the inline function in AccessCompanion.h -- a different file, the
    // SAME unit. Buried: reaching a companion header is not publication. Under the older
    // file-keyed rule this earned an IF_ row whose Source/Destination then rendered "-",
    // since that cell has always dropped callers in the function's own unit.
    int companionFromHeader(int v);

    // Called from AccessCompanionUser.cpp -- a different unit. Published. The control:
    // identical declaration, identical label, so only the caller's unit separates them.
    int companionFromOtherUnit(int v);
};
