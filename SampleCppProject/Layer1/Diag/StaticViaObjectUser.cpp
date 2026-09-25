#include "StaticViaObject.h"

// A SECOND translation unit. The static members are defined in StaticViaObject.cpp, so here
// clang resolves every reference to the in-class DECLARATION, which the parser then folds
// onto the definition -- the member-access form has to land on the same entry as the
// qualified one does.

// A derived class writing its base's PROTECTED static through `this->`, from another unit
// -> In. s_mark still gets no interface row: protected is recorded as private.
void ViaDerived::markFromDerived(void) {
    this->s_mark = 7;
}

// The only use of s_seenOnlyViaObject outside its own unit, and it goes through an object.
// Seeing this read is what publishes the member as an interface of StaticViaObject.
void viaReadFromOtherUnit(void) {
    ViaCounters c;
    int seen = c.s_seenOnlyViaObject;
    (void)seen;
}

// Calls every scenario from another unit, so each one's row and Direction cell reach the
// document.
void viaDriveAll(void) {
    ViaCounters c;
    c.bumpThis();
    c.peekThis();
    c.orThis();
    c.bumpPairThis();
    c.touchField();
    c.callsBumpThis();
    (void)c.getAndBump();
    (void)c.bumpAndReturn();
    viaBumpLocalObject();
    viaBumpByPointer(&c);
    viaBumpPrivateByRef(c);
    viaBumpGlobalObject();
    viaBumpGlobalPointer();
    viaBumpArrayElement(1);
    viaReadCap();
    viaDriveDerived();
}
