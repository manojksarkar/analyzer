#pragma once

// Test: a class whose HEADER STEM DIFFERS from the .cpp that defines its static member
// (StatDefs.h vs ClassStatics.cpp). A stray declaration entry would land in a different
// unit and print as a SECOND interface row for one variable -- the `g_opsTable` shape.
// Exactly one entry, in ClassStatics, is the expected result.
//
// Deliberately NOT annotated PRIVATE/PUBLIC/PROTECTED: visibility for a class member must
// come from the C++ access specifier, the only signal a member has.
class StatRegistry {
public:
    static int s_entries;
};
