#pragma once

// Test: an ORPHAN header (no ViaLimits.cpp) holding a class whose static member is
// initialised IN the class, so it has no out-of-line definition anywhere. The model keeps
// its declaration as the only entry, keyed to this header.
//
// StaticViaObject.cpp reads it through an object (`lim.s_cap`). Seeing that read must not
// move anything in the unit header tables -- the class is already listed by the unit that
// names it, and a class's static member never gets a row of its own -- and must not publish
// it either: a declaration is not an interface.
class ViaLimits {
public:
    static const int s_cap = 8;
    int spare;
};
