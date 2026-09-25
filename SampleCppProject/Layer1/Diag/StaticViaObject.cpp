#include "StaticViaObject.h"

int ViaCounters::s_seenOnlyViaObject = 0;
int ViaCounters::s_public = 0;
ViaPair ViaCounters::s_pair = {0, 0};
int ViaCounters::s_mark = 0;
int ViaCounters::s_private = 0;

ViaCounters g_viaObject;
ViaCounters* g_viaPointer = &g_viaObject;

// Postfix bump through `this->` -> In.
void ViaCounters::bumpThis(void) {
    this->s_mark++;
}

// Reads through `this->` and writes nothing -> Out, and the reason names s_mark.
void ViaCounters::peekThis(void) {
    int seen = this->s_mark;
    (void)seen;
}

// Compound assignment: the old value is read before the new one is stored -> In, with
// s_mark in BOTH sets.
void ViaCounters::orThis(void) {
    this->s_mark |= 1;
}

// Through `this->`, then through a FIELD of the static member -> In on s_pair.
void ViaCounters::bumpPairThis(void) {
    this->s_pair.hits++;
}

// CONTROL: `this->m_count` is a FIELD of the object, not a static member. It must stay out
// of the global sets -> Out, accesses no globals.
void ViaCounters::touchField(void) {
    this->m_count = 1;
}

// Writes nothing itself; bumpThis() does -> In, transitively, naming bumpThis.
void ViaCounters::callsBumpThis(void) {
    bumpThis();
}

// CONTROL for the rule order: a Get name decides before the write is consulted -> Out.
// The write is still recorded; only the direction ignores it.
int ViaCounters::getAndBump(void) {
    this->s_mark++;
    return this->s_mark;
}

// CONTROL for the rule order: a returned value decides before the write -> Out.
int ViaCounters::bumpAndReturn(void) {
    this->s_mark += 5;
    return this->s_mark;
}

// Through a LOCAL object -> In.
void viaBumpLocalObject(void) {
    ViaCounters c;
    c.s_public = 1;
}

// Through a POINTER parameter -> In, s_public read and written. `*p` itself is untouched --
// the member does not live inside the object -- so p is not an output parameter.
void viaBumpByPointer(ViaCounters* p) {
    p->s_public += 2;
}

// Through a REFERENCE parameter, to a PRIVATE static (hence the friend) -> In. s_private
// stays unpublished, and r is not an output parameter.
void viaBumpPrivateByRef(ViaCounters& r) {
    r.s_private++;
}

// Through a GLOBAL object -> In on s_public. g_viaObject is only the way in: it is neither
// read nor written.
void viaBumpGlobalObject(void) {
    g_viaObject.s_public = 4;
}

// Through a GLOBAL pointer -> In on s_public, and g_viaPointer likewise untouched.
void viaBumpGlobalPointer(void) {
    g_viaPointer->s_public = 5;
}

// Through an ARRAY ELEMENT -> In.
void viaBumpArrayElement(int idx) {
    ViaCounters arr[2];
    arr[idx].s_public = 6;
}

// Reads the orphan header's in-class-initialised static through an object -> Out, reads
// s_cap.
void viaReadCap(void) {
    ViaLimits lim;
    int cap = lim.s_cap;
    (void)cap;
}

// Gives ViaDerived::markFromDerived -- defined in StaticViaObjectUser.cpp -- a caller in
// another unit, so its row is in the document.
void viaDriveDerived(void) {
    ViaDerived d;
    d.markFromDerived();
}
