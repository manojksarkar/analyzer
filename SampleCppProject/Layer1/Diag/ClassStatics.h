#pragma once

// Test: `static` DATA MEMBERS -- shared, program-lifetime storage under a class's name.
// Clang parents them on the class, not the translation unit, so they used to be dropped
// from globalVariables.json, from the read/write sets behind the In/Out direction, and
// from every SWE.4 precondition.
//
// Deliberately NOT annotated PRIVATE/PUBLIC/PROTECTED -- visibility here must be read from
// the C++ access specifier. An annotated declaration still wins where one exists.
class StatCounters {
public:
    // Declared here, DEFINED in ClassStatics.cpp: two cursors, one variable, one entry.
    static int s_publicCount;

    // In-class initialised, so there is NO out-of-line definition anywhere. Nothing to
    // collapse onto -- this declaration is the only cursor and must still be recorded.
    static const int s_limit = 7;

    // NOT static: a FIELD_DECL, a different cursor kind. Must never become a global.
    int m_instance;

protected:
    static int s_protectedMark;

private:
    // Recorded (direction and the test specs need it) but unreachable from another unit,
    // so it must NOT be published as an interface row.
    static int s_privateSecret;
};

// All void-returning and free of Get/Set, so direction falls through to the global-access
// rule -- the rule a static member was invisible to. Annotated PUBLIC because nothing in the
// sample calls them across units, and an un-annotated function with no external caller is
// inferred private and dropped from the interface table.
PUBLIC void statBumpPublic(void);
PUBLIC void statReadPublic(void);
PUBLIC void statBumpPrivate(void);
PUBLIC void statBumpIndirect(void);
PUBLIC void statBumpRegistry(void);

// Returns a value, so direction is decided before globals are consulted.
PUBLIC int statReadLimit(void);

// Defined in ClassStaticsUser.cpp -- a SECOND translation unit touching the same member.
PUBLIC void statBumpFromOtherUnit(void);
