#pragma once

#include "ViaLimits.h"

// Test: a class's STATIC data member reached THROUGH AN OBJECT -- `this->s_x`, `obj.s_x`,
// `ref.s_x`, `ptr->s_x`. Legal C++, and the very same storage as `ViaCounters::s_x`, but
// clang spells it differently: a MEMBER_REF_EXPR, like a field access, instead of the
// DECL_REF_EXPR the class-qualified and bare forms give (ClassStatics.h covers those).
// The global-access walker only knew the second shape, so every read and write in this one
// was dropped: a void function whose whole job is `this->s_mark++` read out as
// `Out: accesses no globals` -- the inverse of the truth.
//
// Every scenario is one function, and each comment says the direction it must come out with.
// Two of them are the RULE ORDER held still: a Get name and a returned value still decide
// before any global is looked at, fix or no fix.
//
// Deliberately NOT annotated PUBLIC/PRIVATE/PROTECTED: the C++ label is the only marking.
// Every function is called from StaticViaObjectUser.cpp, another unit, so its row -- and its
// Direction cell -- is in the document.

struct ViaPair {
    int hits;
    int misses;
};

class ViaCounters {
public:
    // Read from another unit ONLY through an object (StaticViaObjectUser.cpp). Nothing else
    // outside this unit touches it, so whether it is published as an interface depends
    // entirely on that read being seen: no row before the fix, a row after.
    static int s_seenOnlyViaObject;

    // Touched only inside this unit, so it stays unpublished either way -- the control
    // for s_seenOnlyViaObject.
    static int s_public;

    static ViaPair s_pair;

    void bumpThis(void);       // this->s_mark++                        -> In
    void peekThis(void);       // reads this->s_mark, writes nothing    -> Out, reason names s_mark
    void orThis(void);         // this->s_mark |= 1                     -> In, s_mark read AND written
    void bumpPairThis(void);   // this->s_pair.hits++, through a field  -> In
    void touchField(void);     // this->m_count = 1: a FIELD, no global -> Out, no globals (control)
    void callsBumpThis(void);  // writes only through bumpThis()        -> In, transitively
    int getAndBump(void);      // Get in the name decides first         -> Out (rule 1, unchanged)
    int bumpAndReturn(void);   // a returned value decides second       -> Out (rule 2, unchanged)

protected:
    // PROTECTED: a derived class in ANOTHER UNIT writes it (ViaDerived). It stays
    // unpublished whatever the fix does -- protected is recorded as private.
    static int s_mark;

    int m_count;

private:
    static int s_private;

    friend void viaBumpPrivateByRef(ViaCounters& r);
};

// A derived class whose method is DEFINED IN ANOTHER UNIT (StaticViaObjectUser.cpp) and
// writes the base's PROTECTED static through `this->`. Its direction is In; s_mark still
// gets no interface row.
class ViaDerived : public ViaCounters {
public:
    void markFromDerived(void);
};

// A global OBJECT and a global POINTER, used only as the way in to a static member.
// Naming them reaches ViaCounters::s_public; it neither reads nor writes them.
extern ViaCounters g_viaObject;
extern ViaCounters* g_viaPointer;

void viaBumpLocalObject(void);               // c.s_public = 1                    -> In
void viaBumpByPointer(ViaCounters* p);       // p->s_public += 2 -> In, read AND written; *p is not written
void viaBumpPrivateByRef(ViaCounters& r);    // r.s_private++    -> In; s_private keeps no row
void viaBumpGlobalObject(void);              // g_viaObject.s_public = 4  -> In on s_public, not g_viaObject
void viaBumpGlobalPointer(void);             // g_viaPointer->s_public = 5 -> In on s_public, not g_viaPointer
void viaBumpArrayElement(int idx);           // arr[idx].s_public = 6     -> In
void viaReadCap(void);                       // lim.s_cap, declared in an orphan header -> Out, reads s_cap
void viaDriveDerived(void);                  // calls ViaDerived::markFromDerived across units
